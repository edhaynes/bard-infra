"""Sprint B6 — console manage actions (feature #64 core).

Written against the contracts FIRST (CLAUDE.md §11): the B6 extensions to
``contracts/control-plane.openapi.yaml`` (rename / workgroup / audit paths,
AuditView) and the additive ``DeviceRecord.workgroup`` in
``contracts/enrollment.schema.json``. Covers:

- DeviceStore.rename / assign_workgroup (persistence, determinism, errors)
- the deterministic v2 workgroup-id derivation (trust.schema WorkgroupId)
- AuditLog: append-only JSONL persistence, injectable clock, newest-first
- the Registry routes: auth, 404s, audit recording with the token subject
- /fleet surfacing the assigned workgroup (the B5 always-null gap, closed)

Hermetic: injected clock, no network, TestClient in-process (§11).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient
from referencing import Registry, Resource

from common.auth import JwtVerifier
from registry.app import create_app
from registry.audit_log import (
    ACTION_APPROVE,
    ACTION_RENAME,
    ACTION_REVOKE,
    ACTION_WORKGROUP,
    AuditLog,
)
from registry.device_store import DeviceNotFound, DeviceStore, derive_workgroup_id
from registry.store import RegistryStore
from tests.fakes.ed25519_helper import public_key_b64_for
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE = ROOT / "contracts" / "control-plane.openapi.yaml"
ENROLLMENT = ROOT / "contracts" / "enrollment.schema.json"
TRUST = ROOT / "contracts" / "trust.schema.yaml"

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholder — NOT a credential.
JOIN_SECRET = "b6-test-join-secret-padding-0123456789-x"  # noqa: S105  # gitleaks:allow
MANAGER = "manager-eddie"


class FakeClock:
    """Deterministic clock (no real time, §11)."""

    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 6, 12, 12, 0, 0, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


def _store(tmp_path: Path | None = None, clock: FakeClock | None = None) -> DeviceStore:
    return DeviceStore(
        (tmp_path / "devices.json") if tmp_path else None,
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock or FakeClock(),
    )


def _pending(store: DeviceStore, device_id: str, label: str | None = None) -> None:
    store.enroll(device_id, store.issue_join_token(ttl_s=600), public_key_b64_for(device_id), label)


# --- contract: the B6 surface is contracted before it is implemented ---------


def test_control_plane_contract_has_b6_paths():
    spec = yaml.safe_load(CONTROL_PLANE.read_text(encoding="utf-8"))
    paths = spec["paths"]
    assert "post" in paths["/devices/{deviceId}/approve"]
    assert "post" in paths["/devices/{deviceId}/revoke"]
    assert "post" in paths["/devices/{deviceId}/rename"]
    assert "post" in paths["/devices/{deviceId}/workgroup"]
    assert "get" in paths["/audit"]
    audit_entry = spec["components"]["schemas"]["AuditEntry"]
    assert audit_entry["required"] == ["at", "actor", "action", "deviceId"]
    # B8 extended the enum ADDITIVELY (plugin-* actions); the B6 four lead it.
    assert audit_entry["properties"]["action"]["enum"][:4] == [
        "approve",
        "revoke",
        "rename",
        "workgroup",
    ]


def _device_record_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(ENROLLMENT.read_text(encoding="utf-8"))
    registry = Registry().with_resource(uri=schema["$id"], resource=Resource.from_contents(schema))
    return jsonschema.Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/DeviceRecord"}, registry=registry
    )


def test_device_record_with_workgroup_matches_extended_contract():
    store = _store()
    _pending(store, "dev-a", label="Front desk PC")
    record = store.assign_workgroup("dev-a", "Front office")
    _device_record_validator().validate(record)


def test_workgroup_id_matches_trust_schema_pattern():
    trust = yaml.safe_load(TRUST.read_text(encoding="utf-8"))
    pattern = trust["$defs"]["WorkgroupId"]["pattern"]
    assert re.fullmatch(pattern, derive_workgroup_id("Front office"))
    assert re.fullmatch(pattern, derive_workgroup_id("ünïcode crew 🛠"))


# --- DeviceStore.rename -------------------------------------------------------


def test_rename_sets_label_and_persists(tmp_path):
    store = _store(tmp_path)
    _pending(store, "dev-a")
    record = store.rename("dev-a", "Reception PC")
    assert record["label"] == "Reception PC"
    assert "secret" not in record
    reloaded = _store(tmp_path)
    assert reloaded.get_device("dev-a")["label"] == "Reception PC"


def test_rename_overwrites_existing_label():
    store = _store()
    _pending(store, "dev-a", label="Old name")
    assert store.rename("dev-a", "New name")["label"] == "New name"


def test_rename_unknown_device_raises():
    with pytest.raises(DeviceNotFound):
        _store().rename("ghost", "Anything")


# --- DeviceStore.assign_workgroup ----------------------------------------------


def test_assign_workgroup_sets_derived_id_and_persists(tmp_path):
    store = _store(tmp_path)
    _pending(store, "dev-a")
    record = store.assign_workgroup("dev-a", "Front office")
    assert record["workgroup"]["name"] == "Front office"
    assert record["workgroup"]["workgroupId"] == derive_workgroup_id("Front office")
    reloaded = _store(tmp_path)
    assert reloaded.get_device("dev-a")["workgroup"] == record["workgroup"]


def test_same_name_yields_same_workgroup_id_across_devices():
    store = _store()
    _pending(store, "dev-a")
    _pending(store, "dev-b")
    a = store.assign_workgroup("dev-a", "Front office")
    b = store.assign_workgroup("dev-b", "Front office")
    assert a["workgroup"]["workgroupId"] == b["workgroup"]["workgroupId"]
    c = store.assign_workgroup("dev-b", "Back office")
    assert c["workgroup"]["workgroupId"] != a["workgroup"]["workgroupId"]


def test_assign_workgroup_none_clears():
    store = _store()
    _pending(store, "dev-a")
    store.assign_workgroup("dev-a", "Front office")
    record = store.assign_workgroup("dev-a", None)
    assert "workgroup" not in record


def test_assign_workgroup_none_when_already_unassigned_is_noop():
    store = _store()
    _pending(store, "dev-a")
    assert "workgroup" not in store.assign_workgroup("dev-a", None)


def test_assign_workgroup_unknown_device_raises():
    with pytest.raises(DeviceNotFound):
        _store().assign_workgroup("ghost", "Front office")


# --- AuditLog -------------------------------------------------------------------


def test_audit_log_records_with_injected_clock_and_newest_first(tmp_path):
    clock = FakeClock()
    log = AuditLog(tmp_path / "audit.jsonl", clock=clock)
    log.record(actor=MANAGER, action=ACTION_APPROVE, device_id="dev-a")
    clock.advance(60)
    log.record(actor=MANAGER, action=ACTION_RENAME, device_id="dev-a", detail="Reception PC")
    entries = log.entries()
    assert [e["action"] for e in entries] == [ACTION_RENAME, ACTION_APPROVE]
    assert entries[0]["at"] == "2026-06-12T12:01:00+00:00"
    assert entries[0]["detail"] == "Reception PC"
    assert entries[1]["actor"] == MANAGER
    assert "detail" not in entries[1]


def test_audit_log_is_append_only_jsonl_and_reloads(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, clock=FakeClock())
    log.record(actor=MANAGER, action=ACTION_REVOKE, device_id="dev-a")
    log.record(actor=MANAGER, action=ACTION_WORKGROUP, device_id="dev-b", detail="Front office")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # one JSON object per line, appended in order
    assert json.loads(lines[0])["action"] == ACTION_REVOKE
    reloaded = AuditLog(path, clock=FakeClock())
    assert [e["action"] for e in reloaded.entries()] == [ACTION_WORKGROUP, ACTION_REVOKE]


def test_audit_log_load_skips_blank_lines(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"at": "t", "actor": "a", "action": "approve", "deviceId": "d"}\n\n')
    assert len(AuditLog(path).entries()) == 1


def test_audit_log_without_path_is_memory_only():
    log = AuditLog(None, clock=FakeClock())
    log.record(actor=MANAGER, action=ACTION_APPROVE, device_id="dev-a")
    assert len(log.entries()) == 1


def test_audit_log_default_clock_is_aware_utc():
    entry = AuditLog(None).record(actor=MANAGER, action=ACTION_APPROVE, device_id="dev-a")
    parsed = _dt.datetime.fromisoformat(entry["at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == _dt.timedelta(0)


# --- the Registry routes ---------------------------------------------------------


def _app(
    *, with_audit: bool = True, clock: FakeClock | None = None
) -> tuple[TestClient, DeviceStore, AuditLog | None]:
    clock = clock or FakeClock()
    device_store = _store(clock=clock)
    audit_log = AuditLog(None, clock=clock) if with_audit else None
    app = create_app(
        RegistryStore(state_path=None),
        JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER),
        device_store=device_store,
        audit_log=audit_log,
    )
    return TestClient(app), device_store, audit_log


def _auth(subject: str = MANAGER) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(subject, secret=TEST_JWT_SECRET)}"}


def test_b6_routes_require_auth():
    client, store, _ = _app()
    _pending(store, "dev-a")
    assert client.post("/devices/dev-a/rename", json={"label": "X"}).status_code == 401
    assert client.post("/devices/dev-a/workgroup", json={"name": "X"}).status_code == 401
    assert client.get("/audit").status_code == 401


def test_rename_route_renames_and_audits():
    client, store, audit_log = _app()
    _pending(store, "dev-a")
    r = client.post("/devices/dev-a/rename", json={"label": "Reception PC"}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["device"]["label"] == "Reception PC"
    (entry,) = audit_log.entries()
    assert entry["actor"] == MANAGER
    assert entry["action"] == ACTION_RENAME
    assert entry["deviceId"] == "dev-a"
    assert entry["detail"] == "Reception PC"


def test_rename_route_unknown_device_404_and_not_audited():
    client, _, audit_log = _app()
    r = client.post("/devices/ghost/rename", json={"label": "X"}, headers=_auth())
    assert r.status_code == 404
    assert audit_log.entries() == []


def test_workgroup_route_assigns_clears_and_audits():
    client, store, audit_log = _app()
    _pending(store, "dev-a")
    r = client.post("/devices/dev-a/workgroup", json={"name": "Front office"}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["device"]["workgroup"]["name"] == "Front office"

    r = client.post("/devices/dev-a/workgroup", json={"name": None}, headers=_auth())
    assert r.status_code == 200
    assert "workgroup" not in r.json()["device"]

    assign, clear = audit_log.entries()[1], audit_log.entries()[0]
    assert assign["action"] == ACTION_WORKGROUP and assign["detail"] == "Front office"
    assert clear["action"] == ACTION_WORKGROUP and "detail" not in clear


def test_workgroup_route_unknown_device_404():
    client, _, _ = _app()
    r = client.post("/devices/ghost/workgroup", json={"name": "X"}, headers=_auth())
    assert r.status_code == 404


def test_approve_and_revoke_routes_audit_the_actor():
    client, store, audit_log = _app()
    _pending(store, "dev-a")
    assert client.post("/devices/dev-a/approve", headers=_auth("alice")).status_code == 200
    assert client.post("/devices/dev-a/revoke", headers=_auth("bob")).status_code == 200
    revoke, approve = audit_log.entries()
    assert (approve["actor"], approve["action"]) == ("alice", ACTION_APPROVE)
    assert (revoke["actor"], revoke["action"]) == ("bob", ACTION_REVOKE)


def test_mutations_work_without_an_audit_log():
    # Wiring without an AuditLog (e.g. device identity on, audit not configured
    # in a bespoke embed) must not break the actions themselves.
    client, store, audit_log = _app(with_audit=False)
    assert audit_log is None
    _pending(store, "dev-a")
    assert client.post("/devices/dev-a/approve", headers=_auth()).status_code == 200
    r = client.post("/devices/dev-a/rename", json={"label": "X"}, headers=_auth())
    assert r.status_code == 200
    # And the read endpoint is simply absent (FastAPI default 404).
    assert client.get("/audit", headers=_auth()).status_code == 404


def test_audit_route_returns_entries_newest_first():
    clock = FakeClock()
    client, store, _ = _app(clock=clock)
    _pending(store, "dev-a")
    client.post("/devices/dev-a/approve", headers=_auth())
    clock.advance(30)
    client.post("/devices/dev-a/rename", json={"label": "Reception PC"}, headers=_auth())
    body = client.get("/audit", headers=_auth()).json()
    assert [e["action"] for e in body["entries"]] == [ACTION_RENAME, ACTION_APPROVE]
    assert body["generatedAt"]


# --- /fleet surfaces the assignment (closes the B5 always-null gap) -------------


def test_fleet_surfaces_assigned_workgroup():
    client, store, _ = _app()
    _pending(store, "dev-a", label="Front desk PC")
    _pending(store, "dev-b")
    client.post("/devices/dev-a/workgroup", json={"name": "Front office"}, headers=_auth())
    rows = {r["id"]: r for r in client.get("/fleet", headers=_auth()).json()["devices"]}
    assert rows["dev-a"]["workgroup"] == {
        "workgroupId": derive_workgroup_id("Front office"),
        "name": "Front office",
    }
    assert rows["dev-b"]["workgroup"] is None
