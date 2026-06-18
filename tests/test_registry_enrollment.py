"""Sprint B2 — Registry HTTP enrollment endpoints (contracts/enrollment.schema.json).

Drives the real Registry FastAPI app (with a DeviceStore injected) through
``/enroll``, ``/devices``, ``/devices/{id}/approve``, ``/devices/{id}/revoke``,
covering the happy path and every auth / error branch. ADR-0016/S3: the enroll
request carries the device's base64 Ed25519 public key; no response returns a
secret. No network: the app is exercised in-process via TestClient; the
join-token + device keypairs are deterministic test placeholders.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.device_store import DeviceStore
from registry.store import RegistryStore
from tests.fakes.ed25519_helper import public_key_b64_for
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholder — NOT a credential.
JOIN_SECRET = "reg-enroll-join-secret-padding-0123456789"  # noqa: S105  # gitleaks:allow
assert len(JOIN_SECRET.encode()) >= 32

PUBKEY = public_key_b64_for("dev-a")


def _app() -> tuple[TestClient, DeviceStore]:
    device_store = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    app = create_app(RegistryStore(state_path=None), verifier, device_store=device_store)
    return TestClient(app), device_store


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def test_enroll_creates_pending_device():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    r = client.post(
        "/enroll",
        json={"deviceId": "dev-a", "joinToken": jt, "publicKey": PUBKEY, "label": "Laptop"},
    )
    assert r.status_code == 200
    assert r.json()["device"]["state"] == "pending"
    assert r.json()["device"]["publicKey"] == PUBKEY
    assert "deviceSecret" not in r.json()["device"]


def test_enroll_bad_join_token_401():
    client, _ = _app()
    r = client.post(
        "/enroll", json={"deviceId": "dev-a", "joinToken": "garbage", "publicKey": PUBKEY}
    )
    assert r.status_code == 401


def test_enroll_bad_public_key_400():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    r = client.post(
        "/enroll", json={"deviceId": "dev-a", "joinToken": jt, "publicKey": "not-base64-!!"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_enroll_missing_public_key_422():
    """publicKey is a required body field now (extra=forbid + min_length)."""
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    r = client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt})
    assert r.status_code == 422


def test_enroll_duplicate_409():
    client, store = _app()
    jt1 = store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt1, "publicKey": PUBKEY})
    jt2 = store.issue_join_token(ttl_s=600)
    r = client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt2, "publicKey": PUBKEY})
    assert r.status_code == 409


def test_approve_activates_without_secret():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt, "publicKey": PUBKEY})
    r = client.post("/devices/dev-a/approve", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["device"]["state"] == "active"
    # The asymmetric upgrade dropped the one-time secret entirely.
    assert "deviceSecret" not in body


def test_approve_unauth_401():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt, "publicKey": PUBKEY})
    r = client.post("/devices/dev-a/approve")
    assert r.status_code == 401


def test_approve_unknown_404():
    client, _ = _app()
    r = client.post("/devices/ghost/approve", headers=_auth())
    assert r.status_code == 404


def test_approve_already_active_409():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt, "publicKey": PUBKEY})
    client.post("/devices/dev-a/approve", headers=_auth())
    r = client.post("/devices/dev-a/approve", headers=_auth())
    assert r.status_code == 409


def test_revoke_marks_revoked():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt, "publicKey": PUBKEY})
    client.post("/devices/dev-a/approve", headers=_auth())
    r = client.post("/devices/dev-a/revoke", headers=_auth())
    assert r.status_code == 200
    assert r.json()["device"]["state"] == "revoked"
    # Revoke wipes the stored public key so the device's tokens stop verifying.
    assert "publicKey" not in r.json()["device"]


def test_revoke_unauth_401():
    client, _ = _app()
    r = client.post("/devices/dev-a/revoke")
    assert r.status_code == 401


def test_revoke_unknown_404():
    client, _ = _app()
    r = client.post("/devices/ghost/revoke", headers=_auth())
    assert r.status_code == 404


def test_list_devices_requires_auth():
    client, _ = _app()
    assert client.get("/devices").status_code == 401


def test_list_devices_returns_records():
    client, store = _app()
    jt = store.issue_join_token(ttl_s=600)
    client.post("/enroll", json={"deviceId": "dev-a", "joinToken": jt, "publicKey": PUBKEY})
    r = client.get("/devices", headers=_auth())
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_enrollment_endpoints_absent_when_device_store_not_injected():
    """When device identity is OFF (no DeviceStore), the enrollment routes are
    not even registered — the fleet-JWT path is unchanged."""
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    client = TestClient(create_app(RegistryStore(state_path=None), verifier))
    jt_free = client.post("/enroll", json={"deviceId": "x", "joinToken": "y", "publicKey": "z"})
    assert jt_free.status_code == 404
