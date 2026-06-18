"""Step S7 — Registry HTTP recovery-escrow endpoints (recovery.schema.json).

Drives the real Registry FastAPI app (DeviceStore + RecoveryStore injected,
authed through a real FleetOrDeviceVerifier exactly as registry/main.py wires
it) through POST /recovery/escrow and GET /recovery/escrow/{handle}, covering
the happy path and every auth / error branch. Validated against the FROZEN
contract (contracts/recovery.schema.json). Hermetic: in-process TestClient, no
network; device keypairs are deterministic placeholders; the wraps are opaque
ciphertext the server never decrypts.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import jsonschema
from fastapi.testclient import TestClient
from referencing import Registry, Resource

from common.auth import JwtVerifier
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from registry.app import create_app
from registry.device_store import DeviceStore
from registry.recovery_store import RecoveryStore
from registry.store import RegistryStore
from tests.fakes.ed25519_helper import keypair_for, mint_device_token, public_key_b64_for
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_CONTRACT = ROOT / "contracts" / "recovery.schema.json"

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholder — NOT a credential.
JOIN_SECRET = "s7-join-secret-padding-0123456789-abcdef"  # noqa: S105  # gitleaks:allow

PW_WRAP = base64.b64encode(b"password-wrapped-seed-ciphertext").decode("ascii")
OMG_WRAP = base64.b64encode(b"omg-code-wrapped-seed-ciphertext").decode("ascii")
PW_WRAP_2 = base64.b64encode(b"rotated-password-wrap-ciphertext").decode("ascii")
OMG_WRAP_2 = base64.b64encode(b"rotated-omg-wrap-ciphertext-here").decode("ascii")


def _app(*, recovery: bool = True) -> tuple[TestClient, DeviceStore]:
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=ISSUER)
    fleet = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    verifier = FleetOrDeviceVerifier(fleet, PerDeviceVerifier(devices, issuer=ISSUER))
    app = create_app(
        RegistryStore(state_path=None),
        verifier,
        device_store=devices,
        recovery_store=RecoveryStore(None) if recovery else None,
    )
    return TestClient(app), devices


def _validator(defn: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(RECOVERY_CONTRACT.read_text())
    registry = Registry().with_resource(uri=schema["$id"], resource=Resource.from_contents(schema))
    return jsonschema.Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/{defn}"}, registry=registry
    )


def _device_auth(device_id: str) -> dict[str, str]:
    private_key, _ = keypair_for(device_id)
    token = mint_device_token(device_id, private_key, issuer=ISSUER, ttl_s=3600)
    return {"Authorization": f"Bearer {token}"}


def _fleet_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def _self_register(client: TestClient, device_id: str) -> None:
    r = client.post(
        "/devices/self-register",
        json={"deviceId": device_id, "publicKey": public_key_b64_for(device_id)},
    )
    assert r.status_code == 200, r.text


def _body(device_id: str = "phone-1", handle: str = "alice@example.com", **wraps) -> dict:
    return {
        "handle": handle,
        "publicKey": public_key_b64_for(device_id),
        "wraps": {"password": wraps.get("password", PW_WRAP), "omg": wraps.get("omg", OMG_WRAP)},
    }


def _escrow(client: TestClient, device_id: str = "phone-1", **kw) -> dict:
    r = client.post(
        "/recovery/escrow", json=_body(device_id, **kw), headers=_device_auth(device_id)
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- POST /recovery/escrow: auth ---------------------------------------------


def test_escrow_requires_auth_401():
    client, _ = _app()
    r = client.post("/recovery/escrow", json=_body())
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_escrow_rejects_bad_token_401():
    client, _ = _app()
    r = client.post("/recovery/escrow", json=_body(), headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_escrow_fleet_token_is_not_a_device_403():
    """A fleet/admin token authenticates but is not an active device — escrow is
    a per-device action, so it is forbidden (403), not allowed."""
    client, _ = _app()
    r = client.post("/recovery/escrow", json=_body(), headers=_fleet_auth())
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_escrow_unregistered_device_token_401():
    """A device that self-signs a valid token but was never registered (or was
    revoked, its key wiped) has no stored public key, so the PerDeviceVerifier
    cannot verify the signature at all -> 401 (the token does not authenticate).
    The 403 'not an active device' branch is for a token that DOES verify but is
    not a device — the fleet token, covered above."""
    client, _ = _app()
    r = client.post("/recovery/escrow", json=_body("phone-1"), headers=_device_auth("phone-1"))
    assert r.status_code == 401


# --- POST /recovery/escrow: happy path + validation --------------------------


def test_escrow_active_device_stores_200():
    client, _ = _app()
    _self_register(client, "phone-1")
    r = client.post("/recovery/escrow", json=_body("phone-1"), headers=_device_auth("phone-1"))
    assert r.status_code == 200, r.text
    body = r.json()
    _validator("EscrowResponse").validate(body)
    assert body == {"handle": "alice@example.com", "status": "stored"}


def test_escrow_request_body_matches_contract():
    _validator("EscrowRequest").validate(_body())


def test_escrow_bad_public_key_400():
    client, _ = _app()
    _self_register(client, "phone-1")
    bad = _body("phone-1")
    bad["publicKey"] = "not-base64-!!"
    r = client.post("/recovery/escrow", json=bad, headers=_device_auth("phone-1"))
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_escrow_missing_wraps_422():
    client, _ = _app()
    _self_register(client, "phone-1")
    r = client.post(
        "/recovery/escrow",
        json={"handle": "alice", "publicKey": public_key_b64_for("phone-1")},
        headers=_device_auth("phone-1"),
    )
    assert r.status_code == 422


def test_escrow_partial_wraps_422():
    client, _ = _app()
    _self_register(client, "phone-1")
    body = _body("phone-1")
    del body["wraps"]["omg"]
    r = client.post("/recovery/escrow", json=body, headers=_device_auth("phone-1"))
    assert r.status_code == 422


def test_escrow_rejects_extra_field_422():
    client, _ = _app()
    _self_register(client, "phone-1")
    body = _body("phone-1")
    body["evil"] = "x"
    r = client.post("/recovery/escrow", json=body, headers=_device_auth("phone-1"))
    assert r.status_code == 422


# --- POST /recovery/escrow: idempotency (OMG rotation) + conflict ------------


def test_escrow_idempotent_same_key_overwrites_wraps():
    client, _ = _app()
    _self_register(client, "phone-1")
    _escrow(client, "phone-1")
    # Re-escrow the SAME handle+key with rotated wraps (OMG rotation).
    _escrow(client, "phone-1", password=PW_WRAP_2, omg=OMG_WRAP_2)
    fetched = client.get("/recovery/escrow/alice@example.com").json()
    assert fetched["wraps"] == {"password": PW_WRAP_2, "omg": OMG_WRAP_2}


def test_escrow_handle_claimed_by_different_key_409():
    client, _ = _app()
    _self_register(client, "phone-1")
    _self_register(client, "phone-2")
    _escrow(client, "phone-1")  # phone-1 claims alice@example.com
    # phone-2 tries to escrow under the same handle with its different key.
    r = client.post("/recovery/escrow", json=_body("phone-2"), headers=_device_auth("phone-2"))
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


# --- GET /recovery/escrow/{handle}: NO auth ----------------------------------


def test_fetch_returns_ciphertext_no_auth():
    client, _ = _app()
    _self_register(client, "phone-1")
    _escrow(client, "phone-1")
    # No Authorization header — a recovering device has no token yet.
    r = client.get("/recovery/escrow/alice@example.com")
    assert r.status_code == 200, r.text
    body = r.json()
    _validator("EscrowFetch").validate(body)
    assert body["publicKey"] == public_key_b64_for("phone-1")
    assert body["wraps"] == {"password": PW_WRAP, "omg": OMG_WRAP}


def test_fetch_unknown_handle_404():
    client, _ = _app()
    r = client.get("/recovery/escrow/nobody@example.com")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# --- routes absent when the store is not wired -------------------------------


def test_escrow_routes_absent_without_recovery_store():
    """Device identity on but no RecoveryStore: the recovery routes are not
    registered (they live in the recovery_store block)."""
    client, _ = _app(recovery=False)
    _self_register(client, "phone-1")
    assert (
        client.post(
            "/recovery/escrow", json=_body("phone-1"), headers=_device_auth("phone-1")
        ).status_code
        == 404
    )
    assert client.get("/recovery/escrow/alice").status_code == 404


def test_escrow_routes_absent_when_device_identity_off():
    """No DeviceStore at all: the recovery block is nested under device identity,
    so the routes do not exist."""
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    client = TestClient(
        create_app(RegistryStore(state_path=None), verifier, recovery_store=RecoveryStore(None))
    )
    assert client.get("/recovery/escrow/alice").status_code == 404
