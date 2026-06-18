"""Sprint B5 — read-only console fleet view (control-plane.openapi.yaml GET /fleet).

Covers the pure join in ``registry/fleet.py`` (every branch: enrollment x
liveness union, connection derivation, label/capabilities/powerProfile
presence, lastSeen fallback, ordering) and the registry app's ``/fleet``
route (auth, with and without a DeviceStore). Hermetic: injected clock, no
network, TestClient in-process.
"""

from __future__ import annotations

import datetime as _dt

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.device_store import DeviceStore
from registry.fleet import build_fleet_view, utcnow_iso
from registry.store import RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholder — NOT a credential.
JOIN_SECRET = "fleet-test-join-secret-padding-0123456789"  # noqa: S105  # gitleaks:allow

GENERATED_AT = "2026-06-12T12:00:00+00:00"
GPU_PROFILE = {"name": "gpu-server", "cpus": 16, "memory": "32g", "gpus": "all"}


def _agent(agent_id: str, status: str, **extra) -> dict:
    record = {"agentId": agent_id, "address": f"{agent_id}.local:8444", "status": status}
    record.update(extra)
    return record


def _device(device_id: str, state: str, **extra) -> dict:
    record = {"deviceId": device_id, "state": state, "createdAt": GENERATED_AT}
    record.update(extra)
    return record


# --- build_fleet_view: the pure join --------------------------------------


def test_empty_fleet():
    view = build_fleet_view([], [], GENERATED_AT)
    assert view == {"devices": [], "generatedAt": GENERATED_AT}


def test_joined_device_online_with_full_agent_record():
    view = build_fleet_view(
        [
            _agent(
                "dev-a",
                "active",
                lastSeen="2026-06-12T11:59:50+00:00",
                capabilities=["gpu", "llm"],
                powerProfile=GPU_PROFILE,
            )
        ],
        [_device("dev-a", "active", label="Front desk PC")],
        GENERATED_AT,
    )
    (row,) = view["devices"]
    assert row == {
        "id": "dev-a",
        "enrollment": "active",
        "connection": "online",
        "lastSeen": "2026-06-12T11:59:50+00:00",
        "workgroup": None,
        "label": "Front desk PC",
        "address": "dev-a.local:8444",
        "capabilities": ["gpu", "llm"],
        "powerProfile": GPU_PROFILE,
    }


def test_stale_agent_maps_to_stale_connection():
    view = build_fleet_view(
        [_agent("dev-b", "stale", lastSeen="2026-06-12T10:00:00+00:00")],
        [_device("dev-b", "active")],
        GENERATED_AT,
    )
    (row,) = view["devices"]
    assert row["connection"] == "stale"
    assert row["lastSeen"] == "2026-06-12T10:00:00+00:00"
    assert "label" not in row  # no label on the enrollment record -> key omitted


def test_enrolled_but_never_started_is_offline():
    view = build_fleet_view([], [_device("dev-c", "pending", label="Warehouse box")], GENERATED_AT)
    (row,) = view["devices"]
    assert row["connection"] == "offline"
    assert row["enrollment"] == "pending"
    assert row["lastSeen"] is None
    assert "address" not in row and "capabilities" not in row and "powerProfile" not in row


def test_pre_identity_agent_has_null_enrollment():
    view = build_fleet_view([_agent("legacy-1", "active")], [], GENERATED_AT)
    (row,) = view["devices"]
    assert row["enrollment"] is None
    # No lastSeen and no registeredAt on the record -> lastSeen None.
    assert row["lastSeen"] is None
    assert "capabilities" not in row and "powerProfile" not in row


def test_last_seen_falls_back_to_registered_at():
    view = build_fleet_view(
        [_agent("dev-d", "stale", registeredAt="2026-06-01T00:00:00+00:00")], [], GENERATED_AT
    )
    assert view["devices"][0]["lastSeen"] == "2026-06-01T00:00:00+00:00"


def test_workgroup_is_null_when_unassigned():
    # B6 populates workgroup from the device record (tests/test_console_manage.py);
    # an unassigned device still reports an explicit null per the contract.
    view = build_fleet_view([_agent("dev-e", "active")], [_device("dev-e", "active")], GENERATED_AT)
    assert view["devices"][0]["workgroup"] is None


def test_rows_sorted_by_display_name_case_insensitive():
    view = build_fleet_view(
        [_agent("zz-agent", "active")],
        [
            _device("dev-2", "active", label="alpha desk"),
            _device("dev-1", "active", label="Bravo desk"),
        ],
        GENERATED_AT,
    )
    names = [r.get("label", r["id"]) for r in view["devices"]]
    assert names == ["alpha desk", "Bravo desk", "zz-agent"]


def test_utcnow_iso_is_aware_utc():
    parsed = _dt.datetime.fromisoformat(utcnow_iso())
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == _dt.timedelta(0)


# --- the /fleet route -------------------------------------------------------


def _registry_app(*, with_devices: bool) -> tuple[TestClient, RegistryStore, DeviceStore | None]:
    store = RegistryStore(state_path=None)
    device_store = (
        DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER) if with_devices else None
    )
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    app = create_app(store, verifier, device_store=device_store)
    return TestClient(app), store, device_store


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def test_fleet_requires_auth():
    client, _, _ = _registry_app(with_devices=True)
    assert client.get("/fleet").status_code == 401


def test_fleet_joins_enrollment_and_heartbeats():
    client, store, device_store = _registry_app(with_devices=True)
    jt = device_store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt, "label": "Front desk PC"})
    store.register("dev-a", "dev-a.local:8444", ["llm"], GPU_PROFILE)

    body = client.get("/fleet", headers=_auth()).json()
    (row,) = body["devices"]
    assert row["id"] == "dev-a"
    assert row["label"] == "Front desk PC"
    assert row["enrollment"] == "pending"
    assert row["connection"] == "online"
    assert row["capabilities"] == ["llm"]
    assert row["powerProfile"] == GPU_PROFILE
    assert body["generatedAt"]


def test_fleet_without_device_store_serves_agents_only():
    client, store, _ = _registry_app(with_devices=False)
    store.register("legacy-1", "legacy-1.local:8444")
    body = client.get("/fleet", headers=_auth()).json()
    (row,) = body["devices"]
    assert row["id"] == "legacy-1"
    assert row["enrollment"] is None
    assert row["connection"] == "online"
