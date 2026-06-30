"""Tests for the control API — full line + branch coverage (TestClient)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from refinery.api import Orchestrator, _cors_origins, create_app
from refinery.sim import ElementState


class _FakeReader:
    """Duck-typed RegistryReader for tests (no network)."""

    def __init__(self, agents: list[dict], *, raise_err: bool = False) -> None:
        self._agents = agents
        self._raise = raise_err
        self.url = "http://reg.test:8081"

    def agents(self) -> list[dict]:
        if self._raise:
            raise httpx.ConnectError("boom")
        return self._agents


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Orchestrator(seed=0)))


def _bring_up(client: TestClient) -> None:
    client.post("/bringup")
    for _ in range(150):
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
    assert s0["plant_minutes"] == 0
    assert s0["plant_minutes_per_tick"] > 0
    assert s0["flagged"] == []
    assert client.post("/step").json()["tick"] == 1
    s1 = client.get("/state").json()
    assert s1["tick"] == 1
    assert s1["plant_minutes"] == s1["plant_minutes_per_tick"]


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
    # resolve kicks off a GRADUAL recovery; step until it completes
    assert client.post(f"/resolve/{inc['seq']}").status_code == 200
    for _ in range(12):
        client.post("/step")
    assert all(i["resolved"] for i in client.get("/state").json()["incidents"])


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


def test_agent_lifecycle_and_state_summary(client):
    assert client.get("/state").json()["agent"]["running"] is False
    st = client.post("/agent/start").json()
    assert st["running"] is True and st["state"] == "monitoring"
    assert client.get("/state").json()["agent"]["running"] is True
    assert client.post("/agent/stop").json()["running"] is False


def test_agent_config_get_set(client):
    cfg = client.get("/agent/config").json()
    assert cfg["provider"] == "vulcan" and "vulcan" in cfg["providers"]
    fake_key = "abcd"  # not a real secret; var so detectors don't keyword-flag it
    out = client.post(
        "/agent/config",
        json={"provider": "groq", "model": "llama-3.3-70b-versatile", "api_key": fake_key},
    ).json()
    assert out["provider"] == "groq" and out["has_key"] is True


def test_agent_prompt_get_set_polish(client):
    assert "operator" in client.get("/agent/prompt").json()["prompt"]
    client.post("/agent/prompt", json={"prompt": "  read   then  heal  "})
    assert client.get("/agent/prompt").json()["prompt"] == "  read   then  heal  "
    assert client.post("/agent/prompt/polish").json()["prompt"] == "read then heal"


def test_agent_mode_valid_and_invalid(client):
    assert client.post("/agent/mode", json={"mode": "approve"}).json()["mode"] == "approve"
    r = client.post("/agent/mode", json={"mode": "wat"})
    assert r.status_code == 400 and "unknown mode" in r.json()["detail"]


def test_agent_auto_heals_via_steps(client):
    client.post("/agent/start")
    client.post("/agent/mode", json={"mode": "auto"})
    client.post("/inject", json={"kind": "element_offline", "target": "TT-1101"})
    for _ in range(8):
        client.post("/step")
    # the safe fault was auto-healed
    state = client.get("/state").json()
    assert all(i["resolved"] for i in state["incidents"])
    assert client.get("/agent/status").json()["state"] in ("monitoring", "remediating")


def test_agent_approve_flow_and_unknown(client):
    client.post("/agent/start")
    client.post("/agent/mode", json={"mode": "approve"})
    client.post("/inject", json={"kind": "switch_down", "target": "S2"})
    client.post("/step")  # detect -> pending
    pending = client.get("/agent/status").json()["pending"]
    assert len(pending) == 1
    ev_id = pending[0]["id"]
    assert client.post(f"/agent/approve/{ev_id}").json()["approved"] is True
    assert client.post("/agent/reject/999").status_code == 404
    # reject path on a fresh pending event
    client.post("/inject", json={"kind": "loss_of_utility", "target": "U-CT1"})
    client.post("/step")
    ev2 = client.get("/agent/status").json()["pending"][0]["id"]
    assert client.post(f"/agent/reject/{ev2}").json()["approved"] is False


def test_agent_approve_unknown_is_404(client):
    assert client.post("/agent/approve/999").status_code == 404


def test_discovery_disconnected_without_registry(client):
    d = client.get("/discovery").json()
    assert d["registry"] == "disconnected" and d["count"] == 0


def test_discovery_connected_and_unreachable():
    agents = [{"agentId": "sensor.S1.TT-1101", "status": "active"}]
    c = TestClient(create_app(Orchestrator(seed=0, registry=_FakeReader(agents))))
    d = c.get("/discovery").json()
    assert d["registry"] == "connected" and d["count"] == 1
    # registry that errors -> unreachable (fail-soft)
    c2 = TestClient(create_app(Orchestrator(seed=0, registry=_FakeReader([], raise_err=True))))
    assert c2.get("/discovery").json()["registry"] == "unreachable"


def test_fleet_sim_only_all_absent_and_reachable(client):
    f = client.get("/fleet").json()
    assert f["registry"] == "disconnected"
    assert f["summary"]["total"] == len(client.get("/elements").json())
    assert all(n["registry"] == "absent" for n in f["nodes"])
    assert f["summary"]["unreachable"] == 0


def test_fleet_connectivity_switch_and_gateway_down(client):
    # switch down -> its section's devices are unreachable behind it
    client.post("/inject", json={"kind": "switch_down", "target": "S2"})
    f = client.get("/fleet").json()
    behind = [
        n
        for n in f["nodes"]
        if n["section"] == "S2" and "switch SW-S2 down" in (n["problem"] or "")
    ]
    assert behind and f["summary"]["unreachable"] > 0


def test_fleet_gateway_down_branch():
    orch = Orchestrator(seed=0)
    orch.sim.set_element_state("GW-S1", ElementState.DOWN)
    f = create_app(orch)  # build app just to reuse orch
    c = TestClient(f)
    fleet = c.get("/fleet").json()
    assert any(n["problem"] == "gateway GW-S1 down" for n in fleet["nodes"])


def test_fleet_registry_stale_marks_unreachable():
    agents = [{"agentId": "sensor.S1.TT-1101", "status": "stale"}]
    c = TestClient(create_app(Orchestrator(seed=0, registry=_FakeReader(agents))))
    f = c.get("/fleet").json()
    node = next(n for n in f["nodes"] if n["tag"] == "TT-1101")
    assert node["registry"] == "stale"
    assert node["problem"] == "heartbeat lost (Registry stale)"
    assert f["summary"]["stale"] >= 1 and f["summary"]["failed"] >= 1


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
