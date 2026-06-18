"""Step S5 — owner identity + box ownership (ADR-0016 §4), contract-first.

The MVP is a user-owned public LokNet: a device self-registers (open bootstrap,
no invite, no manager approval), creates a box (channel) and thereby OWNS it
("the creator is the admin"), and only the owner — or a fleet/admin token — may
invite into and manage that box. This retires the baked fleet token for owner
actions (#67).

The app is driven through a real ``FleetOrDeviceVerifier`` (a per-device token
OR the fleet JWT authenticates owner endpoints), exactly as ``registry/main.py``
wires it when device identity is on. Hermetic: in-process TestClient, no network;
device keypairs are deterministic placeholders (tests/fakes/ed25519_helper).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from fastapi.testclient import TestClient
from referencing import Registry, Resource

from common.auth import JwtVerifier
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from registry.app import create_app
from registry.audit_log import AuditLog
from registry.channel_store import ChannelStore
from registry.device_store import DeviceStore
from registry.store import RegistryStore
from tests.fakes.ed25519_helper import keypair_for, mint_device_token, public_key_b64_for
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ROOT = Path(__file__).resolve().parents[1]
INVITE_CONTRACT = ROOT / "contracts" / "invite.schema.json"
ENROLL_CONTRACT = ROOT / "contracts" / "enrollment.schema.json"

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholders — NOT credentials.
JOIN_SECRET = "s5-join-secret-padding-0123456789-abcdef"  # noqa: S105  # gitleaks:allow
INVITE_SECRET = "s5-invite-secret-padding-0123456789-abcd"  # noqa: S105  # gitleaks:allow
BASE_URL = "https://join.bardllm.dev/i"
assert len(INVITE_SECRET.encode()) >= 32


def _app() -> tuple[TestClient, DeviceStore, ChannelStore]:
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    channels = ChannelStore(
        devices, None, invite_secret=INVITE_SECRET, issuer=ISSUER, invite_base_url=BASE_URL
    )
    fleet = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    verifier = FleetOrDeviceVerifier(fleet, PerDeviceVerifier(devices, issuer=ISSUER))
    app = create_app(
        RegistryStore(state_path=None),
        verifier,
        device_store=devices,
        channel_store=channels,
        default_invite_ttl_s=3600,
        audit_log=AuditLog(None),
    )
    return TestClient(app), devices, channels


def _fleet_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def _device_auth(device_id: str) -> dict[str, str]:
    """An active device's self-signed EdDSA bearer (the device's own token)."""
    private_key, _ = keypair_for(device_id)
    token = mint_device_token(device_id, private_key, issuer=ISSUER, ttl_s=3600)
    return {"Authorization": f"Bearer {token}"}


def _validator(contract: Path, defn: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(contract.read_text())
    enroll = json.loads(ENROLL_CONTRACT.read_text())
    registry = (
        Registry()
        .with_resource(uri=schema["$id"], resource=Resource.from_contents(schema))
        .with_resource(uri=enroll["$id"], resource=Resource.from_contents(enroll))
    )
    return jsonschema.Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/{defn}"}, registry=registry
    )


def _self_register(client: TestClient, device_id: str, **body) -> dict:
    r = client.post(
        "/devices/self-register",
        json={"deviceId": device_id, "publicKey": public_key_b64_for(device_id), **body},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_channel(client: TestClient, channel_id: str, headers: dict, **body) -> dict:
    r = client.post("/channels", json={"channelId": channel_id, **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- self-register (open owner bootstrap) ------------------------------------


def test_self_register_creates_active_device():
    client, _, _ = _app()
    body = _self_register(client, "phone-1", label="Owner")
    _validator(ENROLL_CONTRACT, "SelfRegisterResponse").validate(body)
    assert body["device"]["state"] == "active"
    assert body["device"]["publicKey"] == public_key_b64_for("phone-1")
    assert "deviceSecret" not in body["device"]


def test_self_register_needs_no_auth():
    client, _, _ = _app()
    # No Authorization header at all — the bootstrap is an OPEN endpoint.
    r = client.post(
        "/devices/self-register",
        json={"deviceId": "phone-1", "publicKey": public_key_b64_for("phone-1")},
    )
    assert r.status_code == 200


def test_self_register_idempotent_same_key():
    client, _, _ = _app()
    first = _self_register(client, "phone-1")
    again = _self_register(client, "phone-1")
    assert first == again


def test_self_register_key_mismatch_409():
    client, _, _ = _app()
    _self_register(client, "phone-1")
    r = client.post(
        "/devices/self-register",
        json={"deviceId": "phone-1", "publicKey": public_key_b64_for("a-different-key")},
    )
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


def test_self_register_bad_public_key_400():
    client, _, _ = _app()
    r = client.post(
        "/devices/self-register", json={"deviceId": "phone-1", "publicKey": "not-base64-!!"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_self_register_missing_public_key_422():
    client, _, _ = _app()
    r = client.post("/devices/self-register", json={"deviceId": "phone-1"})
    assert r.status_code == 422


def test_self_register_rejects_extra_field():
    client, _, _ = _app()
    r = client.post(
        "/devices/self-register",
        json={"deviceId": "phone-1", "publicKey": public_key_b64_for("phone-1"), "evil": "x"},
    )
    assert r.status_code == 422


def test_self_register_absent_without_device_store():
    """No DeviceStore (device identity off): the owner bootstrap route is not
    registered (it lives in the device_store block)."""
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    client = TestClient(create_app(RegistryStore(state_path=None), verifier))
    r = client.post(
        "/devices/self-register", json={"deviceId": "x", "publicKey": public_key_b64_for("x")}
    )
    assert r.status_code == 404


# --- POST /channels (a device that creates a box owns it) --------------------


def test_create_channel_requires_auth():
    client, _, _ = _app()
    assert client.post("/channels", json={"channelId": "box-1"}).status_code == 401


def test_device_creating_channel_becomes_owner():
    client, _, channels = _app()
    _self_register(client, "phone-1")
    body = _create_channel(client, "box-1", _device_auth("phone-1"), label="Family")
    _validator(INVITE_CONTRACT, "Channel").validate(body["channel"])
    assert body["channel"] == {"channelId": "box-1", "owner": "phone-1", "label": "Family"}
    assert channels.channel_owner("box-1") == "phone-1"


def test_fleet_token_creates_admin_channel_owner_null():
    client, _, channels = _app()
    body = _create_channel(client, "admin-box", _fleet_auth())
    assert body["channel"]["owner"] is None
    assert channels.channel_owner("admin-box") is None


def test_create_channel_duplicate_409():
    client, _, _ = _app()
    _self_register(client, "phone-1")
    _create_channel(client, "box-1", _device_auth("phone-1"))
    r = client.post("/channels", json={"channelId": "box-1"}, headers=_device_auth("phone-1"))
    assert r.status_code == 409


def test_create_channel_rejects_extra_field():
    client, _, _ = _app()
    r = client.post("/channels", json={"channelId": "box-1", "evil": "x"}, headers=_fleet_auth())
    assert r.status_code == 422


# --- owner-gated invites -----------------------------------------------------


def _own_a_box(client: TestClient) -> None:
    _self_register(client, "owner-phone")
    _create_channel(client, "box-1", _device_auth("owner-phone"))


def test_owner_device_mints_invite_200():
    client, _, _ = _app()
    _own_a_box(client)
    r = client.post("/invites", json={"channelId": "box-1"}, headers=_device_auth("owner-phone"))
    assert r.status_code == 200, r.text
    assert r.json()["invite"]["channelId"] == "box-1"


def test_non_owner_device_invite_403():
    client, _, _ = _app()
    _own_a_box(client)
    # A second active device that does NOT own box-1.
    _self_register(client, "intruder-phone")
    r = client.post("/invites", json={"channelId": "box-1"}, headers=_device_auth("intruder-phone"))
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_fleet_token_bypasses_invite_ownership():
    client, _, _ = _app()
    _own_a_box(client)
    # The admin (fleet) token may invite into a device-owned box.
    r = client.post("/invites", json={"channelId": "box-1"}, headers=_fleet_auth())
    assert r.status_code == 200


# --- owner-gated member management -------------------------------------------


def _add_member(client: TestClient, channel: str, device_id: str, owner_headers: dict) -> None:
    inv = client.post("/invites", json={"channelId": channel}, headers=owner_headers).json()[
        "inviteToken"
    ]
    r = client.post(
        f"/invites/{inv}/redeem",
        json={"deviceId": device_id, "publicKey": public_key_b64_for(device_id)},
    )
    assert r.status_code == 200, r.text


def test_owner_lists_members_200():
    client, _, _ = _app()
    _own_a_box(client)
    _add_member(client, "box-1", "member-1", _device_auth("owner-phone"))
    r = client.get("/channels/box-1/members", headers=_device_auth("owner-phone"))
    assert r.status_code == 200
    assert r.json()["deviceIds"] == ["member-1"]


def test_non_owner_lists_members_403():
    client, _, _ = _app()
    _own_a_box(client)
    _self_register(client, "intruder-phone")
    r = client.get("/channels/box-1/members", headers=_device_auth("intruder-phone"))
    assert r.status_code == 403


def test_owner_removes_member_200():
    client, _, _ = _app()
    _own_a_box(client)
    _add_member(client, "box-1", "member-1", _device_auth("owner-phone"))
    r = client.post("/channels/box-1/members/member-1/remove", headers=_device_auth("owner-phone"))
    assert r.status_code == 200
    assert r.json()["deviceIds"] == []


def test_non_owner_removes_member_403():
    client, _, _ = _app()
    _own_a_box(client)
    _add_member(client, "box-1", "member-1", _device_auth("owner-phone"))
    _self_register(client, "intruder-phone")
    r = client.post(
        "/channels/box-1/members/member-1/remove", headers=_device_auth("intruder-phone")
    )
    assert r.status_code == 403
    # The member is still there (the forbidden remove was a no-op).
    members = client.get("/channels/box-1/members", headers=_fleet_auth()).json()
    assert members["deviceIds"] == ["member-1"]


def test_fleet_token_bypasses_member_management():
    client, _, _ = _app()
    _own_a_box(client)
    _add_member(client, "box-1", "member-1", _device_auth("owner-phone"))
    # Admin lists and removes regardless of device ownership.
    assert client.get("/channels/box-1/members", headers=_fleet_auth()).status_code == 200
    r = client.post("/channels/box-1/members/member-1/remove", headers=_fleet_auth())
    assert r.status_code == 200
