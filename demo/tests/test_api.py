"""Tests for the control API — full line + branch coverage (TestClient)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from refinery.api import Orchestrator, _cors_origins, create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Orchestrator(seed=0)))


def _bring_up(client: TestClient) -> None:
    client.post("/bringup")
    for _ in range(80):
        client.post("/step")
        if client.get("/state").json()["sequencer"]["mode"] == "idle":
            break


# ---------------------------------------------------------------- basics


def test_health_and_version(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/version").json()["version"] == "0.1.0"


def test_state_and_step(client):
    s0 = client.get("/state").json()
    assert s0["tick"] == 0
    assert s0["signals"]["elements_total"] > 0
    assert s0["sequencer"]["mode"] == "idle"
    assert client.post("/step").json()["tick"] == 1
    assert client.get("/state").json()["tick"] == 1


def test_sections_structure(client):
    secs = client.get("/sections").json()
    assert [s["id"] for s in secs] == ["S4", "S1", "S3", "S2", "S5"]
    s1 = next(s for s in secs if s["id"] == "S1")
    assert len(s1["network"]) == 4
    assert any(u["id"] == "U-110" for u in s1["units"])
    el = s1["units"][0]["elements"][0]
    assert {"tag", "agent_id", "value", "state", "in_alarm", "in_trip"} <= set(el)


def test_elements_flat_view(client):
    els = client.get("/elements").json()
    assert len(els) == client.get("/state").json()["signals"]["elements_total"]
    assert all("agent_id" in e for e in els)


def test_faults_menu(client):
    kinds = client.get("/faults").json()
    assert "switch_down" in kinds and kinds["pump_vibration"]["target"] == "pump"


# ---------------------------------------------------------------- operations


def test_bringup_then_running(client):
    assert client.post("/bringup").json()["mode"] == "bringing_up"
    _bring_up(client)
    st = client.get("/state").json()
    assert st["sequencer"]["units_running"] == st["sequencer"]["units_total"]


def test_bringdown(client):
    _bring_up(client)
    assert client.post("/bringdown").json()["mode"] == "bringing_down"


def test_reset_clears_tick(client):
    client.post("/step")
    client.post("/reset")
    assert client.get("/state").json()["tick"] == 0


# ---------------------------------------------------------------- faults


def test_inject_and_resolve(client):
    _bring_up(client)
    inc = client.post("/inject", json={"kind": "unit_trip", "target": "U-840"}).json()
    assert inc["kind"] == "unit_trip" and inc["seq"] == 1
    state = client.get("/state").json()
    assert any(i["seq"] == 1 for i in state["incidents"])
    resolved = client.post(f"/resolve/{inc['seq']}")
    assert resolved.status_code == 200 and resolved.json()["resolved"] is True


def test_inject_bad_kind_is_400(client):
    r = client.post("/inject", json={"kind": "meltdown", "target": "U-840"})
    assert r.status_code == 400
    assert "unknown fault kind" in r.json()["detail"]


def test_inject_bad_target_is_404(client):
    r = client.post("/inject", json={"kind": "unit_trip", "target": "U-GHOST"})
    assert r.status_code == 404
    assert "unknown unit" in r.json()["detail"]


def test_resolve_unknown_is_404(client):
    r = client.post("/resolve/999")
    assert r.status_code == 404
    assert "unknown incident" in r.json()["detail"]


# ---------------------------------------------------------------- config


def test_cors_origins_default_and_override(monkeypatch):
    monkeypatch.delenv("REFINERY_CORS_ORIGINS", raising=False)
    assert "http://localhost:5175" in _cors_origins()
    monkeypatch.setenv("REFINERY_CORS_ORIGINS", "https://a.test, https://b.test")
    assert _cors_origins() == ["https://a.test", "https://b.test"]


def test_history_accumulates_and_filters(client):
    for _ in range(4):
        client.post("/step")
    allh = client.get("/history").json()
    assert len(allh["ticks"]) == 4
    assert allh["ticks"][-1] == 4
    assert len(next(iter(allh["series"].values()))) == 4
    # filtered subset (unknown tag ignored)
    sub = client.get("/history?tags=TT-1101,NOPE").json()
    assert set(sub["series"]) == {"TT-1101"}


def test_graph_nodes_and_edges(client):
    g = client.get("/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert {"U-900", "U-840", "U-110"} <= ids
    # the steam boiler -> FCC dependency edge exists
    assert any(e["src"] == "U-900" and e["dst"] == "U-840" for e in g["edges"])
    assert all("status" in n for n in g["nodes"])


def test_netgraph_device_topology(client):
    g = client.get("/netgraph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert "PLANT" in ids
    assert "TT-1101" in ids  # a crude-unit sensor
    types = {n["type"] for n in g["nodes"]}
    assert {"sensor", "valve", "dcs", "switch", "gateway", "workstation", "plant"} <= types
    # gateways wire up to the plant core
    assert any(e["dst"] == "PLANT" for e in g["edges"])
    # a field device wires to its unit controller (U-110 has DCS-110)
    assert any(e["src"] == "TT-1101" and e["dst"] == "DCS-110" for e in g["edges"])
    # a controllerless unit's field device wires straight to the section switch
    assert any(e["src"] == "XV-TF13" and e["dst"] == "SW-S5" for e in g["edges"])


def test_serves_console_static_when_dist_set(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><body>REFINERY</body></html>")
    monkeypatch.setenv("REFINERY_CONSOLE_DIST", str(tmp_path))
    c = TestClient(create_app(Orchestrator(seed=0)))
    # API still works (routes take precedence over the "/" mount)...
    assert c.get("/healthz").json()["status"] == "ok"
    # ...and the SPA is served at root.
    assert "REFINERY" in c.get("/").text


def test_no_static_mount_when_dist_missing(tmp_path, monkeypatch):
    # set to a path that is not a directory -> no mount, root 404s
    monkeypatch.setenv("REFINERY_CONSOLE_DIST", str(tmp_path / "nope"))
    c = TestClient(create_app(Orchestrator(seed=0)))
    assert c.get("/").status_code == 404
