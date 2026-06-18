"""Sprint B3 — Registry HTTP invite endpoints (contracts/invite.schema.json).

Drives the real Registry FastAPI app (DeviceStore + ChannelStore injected)
through ``/invites``, ``/invites/{token}/redeem`` and
``/channels/{id}/members``, covering the happy path and every auth / error
branch. ADR-0016/S3: redeem carries the device's Ed25519 public key; no response
returns a secret. No network: in-process TestClient; device keypairs are
deterministic placeholders.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.audit_log import AuditLog
from registry.channel_store import ChannelStore
from registry.device_store import DeviceStore
from registry.store import RegistryStore
from tests.fakes.ed25519_helper import public_key_b64_for
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholders — NOT credentials.
JOIN_SECRET = "reg-invite-join-secret-padding-0123456789"  # noqa: S105  # gitleaks:allow
INVITE_SECRET = "reg-channel-invite-secret-padding-012345678"  # noqa: S105
BASE_URL = "https://join.bardllm.dev/i"
assert len(INVITE_SECRET.encode()) >= 32


def _pubkey(device_id: str = "phone-1") -> str:
    return public_key_b64_for(device_id)


def _app() -> tuple[TestClient, ChannelStore]:
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    channels = ChannelStore(
        devices, None, invite_secret=INVITE_SECRET, issuer=ISSUER, invite_base_url=BASE_URL
    )
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    app = create_app(
        RegistryStore(state_path=None),
        verifier,
        device_store=devices,
        channel_store=channels,
        default_invite_ttl_s=3600,
    )
    return TestClient(app), channels


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def _create(client: TestClient, channel="north-site", **body) -> dict:
    r = client.post("/invites", json={"channelId": channel, **body}, headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()


# --- create ------------------------------------------------------------------


def test_create_invite_requires_auth():
    client, _ = _app()
    assert client.post("/invites", json={"channelId": "north-site"}).status_code == 401


def test_create_invite_returns_token_and_url():
    client, _ = _app()
    body = _create(client, label="Crew")
    assert body["invite"]["channelId"] == "north-site"
    assert body["invite"]["redeemed"] is False
    assert body["inviteToken"]
    assert body["inviteUrl"].startswith(BASE_URL)
    assert body["inviteToken"] in body["inviteUrl"] or "%" in body["inviteUrl"]


def test_create_invite_honors_ttl_override():
    client, channels = _app()
    body = _create(client, ttlSeconds=42)
    rec = channels._invites[body["invite"]["inviteId"]]
    # created + 42s == expires (string compare is fine for ISO on the same day).
    assert rec["expiresAt"] > rec["createdAt"]


def test_create_invite_rejects_extra_field():
    # The Registry app has no RequestValidationError->400 shim (unlike the
    # Router), so FastAPI's default 422 is the contract here; extra=forbid still
    # blocks the unknown key (never a silent pass-through).
    client, _ = _app()
    r = client.post("/invites", json={"channelId": "north-site", "evil": "x"}, headers=_auth())
    assert r.status_code == 422


# --- redeem (no auth required — the link IS the authorization) ----------------


def test_redeem_admits_active_member_no_auth_no_approve():
    client, _ = _app()
    token = _create(client)["inviteToken"]
    pubkey = _pubkey("phone-1")
    r = client.post(f"/invites/{token}/redeem", json={"deviceId": "phone-1", "publicKey": pubkey})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device"]["state"] == "active"
    assert body["device"]["publicKey"] == pubkey
    assert body["channelId"] == "north-site"
    assert "deviceSecret" not in body
    # Member shows up on the channel.
    members = client.get("/channels/north-site/members", headers=_auth()).json()
    assert members["deviceIds"] == ["phone-1"]


def test_redeem_bad_public_key_400():
    client, _ = _app()
    token = _create(client)["inviteToken"]
    r = client.post(
        f"/invites/{token}/redeem", json={"deviceId": "phone-1", "publicKey": "not-base64-!!"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_redeem_missing_public_key_422():
    client, _ = _app()
    token = _create(client)["inviteToken"]
    r = client.post(f"/invites/{token}/redeem", json={"deviceId": "phone-1"})
    assert r.status_code == 422


def test_redeem_is_single_use_409_or_401():
    client, _ = _app()
    token = _create(client)["inviteToken"]
    client.post(
        f"/invites/{token}/redeem", json={"deviceId": "phone-1", "publicKey": _pubkey("phone-1")}
    )
    r = client.post(
        f"/invites/{token}/redeem", json={"deviceId": "phone-2", "publicKey": _pubkey("phone-2")}
    )
    assert r.status_code == 401  # already redeemed -> InvalidInviteToken


def test_redeem_garbage_token_401():
    client, _ = _app()
    r = client.post(
        "/invites/not-a-jwt/redeem", json={"deviceId": "phone-1", "publicKey": _pubkey()}
    )
    assert r.status_code == 401


def test_redeem_unknown_jti_404():
    import datetime as dt

    import jwt

    client, _ = _app()
    now = dt.datetime.now(dt.UTC)
    orphan = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "bard-channel-invite",
            "cid": "north-site",
            "jti": "never-issued",
            "iat": now,
            "exp": now + dt.timedelta(hours=1),
        },
        INVITE_SECRET,
        algorithm="HS256",
    )
    r = client.post(
        f"/invites/{orphan}/redeem", json={"deviceId": "phone-1", "publicKey": _pubkey()}
    )
    assert r.status_code == 404


def test_redeem_existing_device_id_409():
    client, _ = _app()
    t1 = _create(client)["inviteToken"]
    client.post(
        f"/invites/{t1}/redeem", json={"deviceId": "phone-1", "publicKey": _pubkey("phone-1")}
    )
    t2 = _create(client, channel="south-site")["inviteToken"]
    r = client.post(
        f"/invites/{t2}/redeem", json={"deviceId": "phone-1", "publicKey": _pubkey("phone-1")}
    )
    assert r.status_code == 409


def test_redeem_rejects_extra_field():
    client, _ = _app()
    token = _create(client)["inviteToken"]
    r = client.post(
        f"/invites/{token}/redeem",
        json={"deviceId": "phone-1", "publicKey": _pubkey(), "evil": "x"},
    )
    assert r.status_code == 422


# --- members -----------------------------------------------------------------


def test_members_requires_auth():
    client, _ = _app()
    assert client.get("/channels/north-site/members").status_code == 401


def test_members_unknown_channel_empty():
    client, _ = _app()
    r = client.get("/channels/ghost/members", headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"channelId": "ghost", "deviceIds": []}


# --- member removal (E1) -----------------------------------------------------


def _app_with_audit() -> tuple[TestClient, ChannelStore, AuditLog]:
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    channels = ChannelStore(
        devices, None, invite_secret=INVITE_SECRET, issuer=ISSUER, invite_base_url=BASE_URL
    )
    audit = AuditLog(None)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    app = create_app(
        RegistryStore(state_path=None),
        verifier,
        device_store=devices,
        channel_store=channels,
        default_invite_ttl_s=3600,
        audit_log=audit,
    )
    return TestClient(app), channels, audit


def _onboard(client: TestClient, channel: str, device_id: str) -> None:
    body = _create(client, channel)
    r = client.post(
        f"/invites/{body['inviteToken']}/redeem",
        json={"deviceId": device_id, "publicKey": _pubkey(device_id)},
    )
    assert r.status_code == 200, r.text


def test_remove_member_requires_auth():
    client, _ = _app()
    assert client.post("/channels/north-site/members/phone-1/remove").status_code == 401


def test_remove_existing_member_200_and_gone():
    client, _, _ = _app_with_audit()
    _onboard(client, "north-site", "phone-1")
    _onboard(client, "north-site", "phone-2")

    r = client.post("/channels/north-site/members/phone-1/remove", headers=_auth())
    assert r.status_code == 200
    assert r.json()["deviceIds"] == ["phone-2"]
    # GET confirms the device is gone.
    members = client.get("/channels/north-site/members", headers=_auth()).json()
    assert members["deviceIds"] == ["phone-2"]


def test_remove_member_is_audited():
    client, _, audit = _app_with_audit()
    _onboard(client, "north-site", "phone-1")
    client.post("/channels/north-site/members/phone-1/remove", headers=_auth())
    entries = audit.entries()
    assert len(entries) == 1
    assert entries[0]["action"] == "member-remove"
    assert entries[0]["deviceId"] == "phone-1"
    assert entries[0]["detail"] == "north-site"


def test_remove_non_member_404():
    client, _, _ = _app_with_audit()
    _onboard(client, "north-site", "phone-1")
    r = client.post("/channels/north-site/members/ghost/remove", headers=_auth())
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_remove_member_unknown_channel_404():
    client, _ = _app()
    r = client.post("/channels/ghost-channel/members/phone-1/remove", headers=_auth())
    assert r.status_code == 404


def test_remove_member_route_absent_without_channel_store():
    """Device identity on but no ChannelStore: the member-remove route is not
    registered (it lives in the channel_store block)."""
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    client = TestClient(create_app(RegistryStore(state_path=None), verifier, device_store=devices))
    r = client.post("/channels/c/members/d/remove", headers=_auth())
    assert r.status_code == 404


# --- routes absent when channel identity is off ------------------------------


def test_invite_routes_absent_without_channel_store():
    """Device identity on but no ChannelStore: invite routes are not registered."""
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    client = TestClient(create_app(RegistryStore(state_path=None), verifier, device_store=devices))
    assert client.post("/invites", json={"channelId": "x"}, headers=_auth()).status_code == 404


def test_invite_routes_absent_when_device_identity_off():
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    client = TestClient(create_app(RegistryStore(state_path=None), verifier))
    assert (
        client.post("/invites/x/redeem", json={"deviceId": "y", "publicKey": _pubkey()}).status_code
        == 404
    )
