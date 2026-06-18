"""Sprint B2 — per-device identity, contract-first (ADR-0010; asymmetric S3).

Tests are written against ``contracts/enrollment.schema.json`` BEFORE the
implementation (CLAUDE.md §11). They pin the enrollment state machine
(join-token -> pending -> active -> revoked), per-device key isolation (a token
self-signed by device A is rejected when presented as device B), and rejection
of unknown / not-yet-approved / revoked devices.

ADR-0016/S3 flipped identity from symmetric (server-minted HMAC secret) to
asymmetric: the device generates an Ed25519 keypair, registers only the public
key, and self-signs EdDSA JWTs. The suite plays the device side via
``tests/fakes/ed25519_helper`` — deterministic keypairs from fixed seeds, no
real randomness, no real clock.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from common.auth import AuthError
from common.device_auth import PerDeviceVerifier
from registry.device_store import (
    DeviceNotFound,
    DeviceStore,
    InvalidJoinToken,
    InvalidPublicKey,
    InvalidStateTransition,
)
from tests.fakes.ed25519_helper import keypair_for, mint_device_token, public_key_b64_for

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "enrollment.schema.json"

ISSUER = "bardllm-pro"
# Join-token signing secret. Obvious >=32-byte placeholder — NOT a credential.
JOIN_SECRET = "join-token-secret-padding-0123456789-abc"  # noqa: S105
assert len(JOIN_SECRET.encode()) >= 32


class FakeClock:
    """Deterministic monotonic-ish clock for the store/verifier (no sleeping)."""

    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 6, 12, 12, 0, 0, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


def _store(tmp_path: Path, clock: FakeClock) -> DeviceStore:
    return DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
    )


def _enroll_approve(store: DeviceStore, device_id: str):
    """Enroll + approve ``device_id`` with a fresh keypair; return its private
    key (the device side) so the test can self-sign tokens."""
    private_key, public_key = keypair_for(device_id)
    store.enroll(device_id, store.issue_join_token(ttl_s=600), public_key)
    store.approve(device_id)
    return private_key


def _contract_validator(defn: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(CONTRACT.read_text())
    registry = Registry().with_resource(uri=schema["$id"], resource=Resource.from_contents(schema))
    return jsonschema.Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/{defn}"}, registry=registry
    )


# --- contract conformance ----------------------------------------------------


def test_device_record_matches_contract(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    record = store.enroll("dev-a", jt, public_key_b64_for("dev-a"), label="Alice's laptop")
    _contract_validator("DeviceRecord").validate(record)
    assert record["state"] == "pending"
    assert record["deviceId"] == "dev-a"
    assert record["label"] == "Alice's laptop"
    # The public key IS part of the record (it is public material); no secret is.
    assert record["publicKey"] == public_key_b64_for("dev-a")
    assert "deviceSecret" not in record


def test_approve_response_matches_contract(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key_b64_for("dev-a"))
    record = store.approve("dev-a")
    _contract_validator("ApproveResponse").validate({"device": record})
    assert record["state"] == "active"
    # No secret returned anymore; the device holds its own private key.
    assert "deviceSecret" not in record


# --- enrollment state machine ------------------------------------------------


def test_full_lifecycle_join_pending_active_then_sign_and_verify(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)

    private_key, public_key = keypair_for("dev-a")
    jt = store.issue_join_token(ttl_s=600)
    pending = store.enroll("dev-a", jt, public_key)
    assert pending["state"] == "pending"

    record = store.approve("dev-a")
    assert record["state"] == "active"

    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    claims = verifier.verify(token)
    assert claims["sub"] == "dev-a"


def test_revoked_device_verify_fails(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)

    private_key = _enroll_approve(store, "dev-a")
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    # Valid while active.
    verifier.verify(token)

    store.revoke("dev-a")
    assert store.get_device("dev-a")["state"] == "revoked"
    # The public key was wiped on revoke.
    assert "publicKey" not in store.get_device("dev-a")
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_pending_device_cannot_verify(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    private_key, public_key = keypair_for("dev-a")
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key)
    # A pending device's key is not active yet, so even a correctly self-signed
    # token is rejected because the store yields no key for a pending device.
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_approve_requires_pending(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key_b64_for("dev-a"))
    store.approve("dev-a")
    # Re-approving an already-active device is an invalid transition.
    with pytest.raises(InvalidStateTransition):
        store.approve("dev-a")


def test_revoke_unknown_device_raises(tmp_path):
    store = _store(tmp_path, FakeClock())
    with pytest.raises(DeviceNotFound):
        store.revoke("ghost")


def test_approve_unknown_device_raises(tmp_path):
    store = _store(tmp_path, FakeClock())
    with pytest.raises(DeviceNotFound):
        store.approve("ghost")


def test_get_unknown_device_raises(tmp_path):
    store = _store(tmp_path, FakeClock())
    with pytest.raises(DeviceNotFound):
        store.get_device("ghost")


# --- public-key validation (S3) ----------------------------------------------


def test_enroll_rejects_missing_public_key(tmp_path):
    store = _store(tmp_path, FakeClock())
    jt = store.issue_join_token(ttl_s=600)
    with pytest.raises(InvalidPublicKey, match="required"):
        store.enroll("dev-a", jt, "")


def test_enroll_rejects_non_base64_public_key(tmp_path):
    store = _store(tmp_path, FakeClock())
    jt = store.issue_join_token(ttl_s=600)
    with pytest.raises(InvalidPublicKey, match="base64"):
        store.enroll("dev-a", jt, "not!base64!!")


def test_enroll_rejects_wrong_length_public_key(tmp_path):
    import base64

    store = _store(tmp_path, FakeClock())
    jt = store.issue_join_token(ttl_s=600)
    # Valid base64 but only 16 bytes — not an Ed25519 key.
    short = base64.b64encode(b"\x01" * 16).decode("ascii")
    with pytest.raises(InvalidPublicKey, match="32 bytes"):
        store.enroll("dev-a", jt, short)


def test_admit_rejects_bad_public_key(tmp_path):
    store = _store(tmp_path, FakeClock())
    with pytest.raises(InvalidPublicKey):
        store.admit("dev-a", "not-base64-!!")


# --- join-token validation ---------------------------------------------------


def test_enroll_rejects_bad_join_token(tmp_path):
    store = _store(tmp_path, FakeClock())
    with pytest.raises(InvalidJoinToken):
        store.enroll("dev-a", "not-a-valid-join-token", public_key_b64_for("dev-a"))


def test_enroll_rejects_expired_join_token(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=60)
    clock.advance(120)
    with pytest.raises(InvalidJoinToken):
        store.enroll("dev-a", jt, public_key_b64_for("dev-a"))


def test_enroll_duplicate_device_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt1 = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt1, public_key_b64_for("dev-a"))
    jt2 = store.issue_join_token(ttl_s=600)
    with pytest.raises(InvalidStateTransition):
        store.enroll("dev-a", jt2, public_key_b64_for("dev-a"))


# --- per-device key isolation ------------------------------------------------


def test_token_for_a_rejected_as_b(tmp_path):
    """A token self-signed with device A's private key but carrying sub=dev-b
    must be rejected: B's stored public key won't verify A's signature."""
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)

    private_a = _enroll_approve(store, "dev-a")
    _enroll_approve(store, "dev-b")

    # Sign with A's private key but claim to be B.
    cross = mint_device_token("dev-b", private_a, issuer=ISSUER, ttl_s=3600, now=clock())
    with pytest.raises(AuthError):
        verifier.verify(cross)


def test_each_device_gets_a_distinct_public_key(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    for dev in ("dev-a", "dev-b"):
        jt = store.issue_join_token(ttl_s=600)
        store.enroll(dev, jt, public_key_b64_for(dev))
        store.approve(dev)
    assert store.device_public_key("dev-a") != store.device_public_key("dev-b")


# --- unknown device rejected -------------------------------------------------


def test_unknown_device_token_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    # A token for a deviceId that was never enrolled.
    private_key, _ = keypair_for("ghost")
    token = mint_device_token("ghost", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_hs256_token_rejected(tmp_path):
    """A device must self-sign EdDSA; an HS256 token (the retired symmetric
    credential) is rejected at the algorithm gate even for an active device."""
    import jwt  # PyJWT

    clock = FakeClock()
    store = _store(tmp_path, clock)
    _enroll_approve(store, "dev-a")
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    now = clock()
    hs = jwt.encode(
        {"sub": "dev-a", "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        "an-hmac-secret-padding-0123456789-abcdef",  # noqa: S106  # gitleaks:allow
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        verifier.verify(hs)


def test_token_without_sub_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    private_key, _ = keypair_for("dev-a")
    now = clock()
    import jwt  # PyJWT

    bad = jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        private_key,
        algorithm="EdDSA",
    )
    with pytest.raises(AuthError):
        verifier.verify(bad)


def test_token_malformed_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    with pytest.raises(AuthError):
        verifier.verify("not.a.jwt")


def test_corrupted_stored_key_fails_closed(tmp_path):
    """Defence in depth: a stored public key that has been corrupted on disk
    makes verification fail closed (AuthError), not crash the request."""
    clock = FakeClock()
    store = _store(tmp_path, clock)
    private_key = _enroll_approve(store, "dev-a")
    # Corrupt the persisted key to a valid-base64 but wrong-length value.
    store._devices["dev-a"]["publicKey"] = "QUJD"  # base64("ABC"), 3 bytes
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    with pytest.raises(AuthError, match="invalid"):
        verifier.verify(token)


# --- persistence round-trip --------------------------------------------------


def test_store_persists_and_reloads(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    private_key, public_key = keypair_for("dev-a")
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key)
    store.approve("dev-a")

    # A fresh store over the same file sees the active device and its public key.
    reloaded = DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
    )
    assert reloaded.get_device("dev-a")["state"] == "active"
    assert reloaded.device_public_key("dev-a") == public_key
    verifier = PerDeviceVerifier(reloaded, issuer=ISSUER, clock=clock)
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    assert verifier.verify(token)["sub"] == "dev-a"


def test_list_devices(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key_b64_for("dev-a"))
    listing = store.list_devices()
    assert len(listing) == 1
    _contract_validator("DeviceList").validate(listing)


def test_store_without_path_does_not_persist(tmp_path):
    store = DeviceStore(
        None,
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=FakeClock(),
    )
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key_b64_for("dev-a"))
    assert store.get_device("dev-a")["state"] == "pending"


# --- owner self-register (ADR-0016 / Step S5) --------------------------------


def test_self_register_creates_active_device(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    public_key = public_key_b64_for("phone-1")
    record = store.self_register("phone-1", public_key, "Owner phone")
    _contract_validator("DeviceRecord").validate(record)
    assert record["state"] == "active"
    assert record["publicKey"] == public_key
    assert record["label"] == "Owner phone"
    # ACTIVE means the key resolves for verification immediately (no approve).
    assert store.device_public_key("phone-1") == public_key


def test_self_register_idempotent_same_key(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    public_key = public_key_b64_for("phone-1")
    first = store.self_register("phone-1", public_key)
    again = store.self_register("phone-1", public_key)
    assert first == again


def test_self_register_key_mismatch_conflicts(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    store.self_register("phone-1", public_key_b64_for("phone-1"))
    with pytest.raises(InvalidStateTransition, match="different public key"):
        store.self_register("phone-1", public_key_b64_for("other-key"))


def test_self_register_bad_public_key_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    with pytest.raises(InvalidPublicKey):
        store.self_register("phone-1", "not-base64-!!")
    # Nothing was persisted for the failed registration.
    with pytest.raises(DeviceNotFound):
        store.get_device("phone-1")


def test_self_register_persists(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    public_key = public_key_b64_for("phone-1")
    store.self_register("phone-1", public_key)
    reloaded = _store(tmp_path, clock)
    assert reloaded.device_public_key("phone-1") == public_key


# --- guard branches ----------------------------------------------------------


def test_device_store_requires_join_secret(tmp_path):
    with pytest.raises(ValueError, match="join_token_secret is required"):
        DeviceStore(None, join_token_secret="", issuer=ISSUER)


def test_verifier_uses_real_clock_when_none(tmp_path):
    """With no injected clock, exp is validated against real UTC (production
    path). A token minted just now (real time) verifies; an already-expired one
    is rejected by PyJWT's own verify_exp."""
    store = DeviceStore(tmp_path / "devices.json", join_token_secret=JOIN_SECRET, issuer=ISSUER)
    private_key, public_key = keypair_for("dev-a")
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt, public_key)
    store.approve("dev-a")
    verifier = PerDeviceVerifier(store, issuer=ISSUER)  # clock=None
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600)
    assert verifier.verify(token)["sub"] == "dev-a"

    expired = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=-3600)
    with pytest.raises(AuthError):
        verifier.verify(expired)


def test_verifier_injected_clock_detects_expiry(tmp_path):
    """With an injected clock, an exp earlier than the clock's now is rejected
    by our own check (covers the clock-present expiry branch)."""
    clock = FakeClock()
    store = _store(tmp_path, clock)
    private_key = _enroll_approve(store, "dev-a")
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=60, now=clock())
    verifier.verify(token)  # valid now
    clock.advance(120)  # advance past exp
    with pytest.raises(AuthError):
        verifier.verify(token)


# --- Sprint B4: FleetOrDeviceVerifier (relay-auth coexistence, bug #56) -------
# The Router's data path accepts EITHER the fleet JWT (legacy agents) OR a
# per-device token, so enabling device identity is a migration, not a flag-day.


def _fleet_or_device(tmp_path, clock):
    from common.auth import JwtVerifier
    from common.device_auth import FleetOrDeviceVerifier

    fleet_secret = "fleet-jwt-secret-padding-0123456789-abcd"  # noqa: S105  # gitleaks:allow
    store = _store(tmp_path, clock)
    composite = FleetOrDeviceVerifier(
        JwtVerifier(fleet_secret, "HS256", ISSUER),
        PerDeviceVerifier(store, issuer=ISSUER, clock=clock),
    )
    return composite, store, fleet_secret


def test_fleet_or_device_accepts_fleet_jwt(tmp_path):
    import datetime as dt

    import jwt as pyjwt

    clock = FakeClock()
    composite, _, fleet_secret = _fleet_or_device(tmp_path, clock)
    now = dt.datetime.now(dt.UTC)
    token = pyjwt.encode(
        {"sub": "agent-x", "iss": ISSUER, "iat": now, "exp": now + dt.timedelta(hours=1)},
        fleet_secret,
        algorithm="HS256",
    )
    assert composite.verify(token)["sub"] == "agent-x"


def test_fleet_or_device_falls_back_to_device_token(tmp_path):
    clock = FakeClock()
    composite, store, _ = _fleet_or_device(tmp_path, clock)
    private_key = _enroll_approve(store, "dev-a")
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    # Fails the fleet verifier (EdDSA vs HMAC), passes the per-device verifier.
    assert composite.verify(token)["sub"] == "dev-a"


def test_fleet_or_device_rejects_token_failing_both(tmp_path):
    clock = FakeClock()
    composite, store, _ = _fleet_or_device(tmp_path, clock)
    private_key = _enroll_approve(store, "dev-a")
    token = mint_device_token("dev-a", private_key, issuer=ISSUER, ttl_s=3600, now=clock())
    store.revoke("dev-a")
    # Revoked: neither the fleet key nor a device key verifies it.
    with pytest.raises(AuthError, match="not active"):
        composite.verify(token)


# --- Sprint B4: reload_on_read — Registry-side revoke reaches the Router ------
# The Router's verifier holds its OWN DeviceStore over the JSON file the
# Registry writes. reload_on_read re-reads the file at each key lookup, so an
# approve/revoke takes effect on the next relay request without a restart.


def test_reload_on_read_sees_cross_instance_revoke(tmp_path):
    clock = FakeClock()
    writer = _store(tmp_path, clock)  # the Registry's store (writes the file)
    reader = DeviceStore(  # the Router's store (reads the same file)
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
        reload_on_read=True,
    )
    public_key = public_key_b64_for("dev-a")
    writer.enroll("dev-a", writer.issue_join_token(ttl_s=600), public_key)
    writer.approve("dev-a")
    assert reader.device_public_key("dev-a") == public_key  # approve visible

    writer.revoke("dev-a")
    assert reader.device_public_key("dev-a") is None  # revoke visible, no restart


def test_snapshot_store_misses_cross_instance_revoke(tmp_path):
    """The default (reload_on_read=False) is a boot-time snapshot — pinning WHY
    the Router must opt in: without reload, a Registry-side revoke would keep
    verifying until restart."""
    clock = FakeClock()
    writer = _store(tmp_path, clock)
    public_key = public_key_b64_for("dev-a")
    writer.enroll("dev-a", writer.issue_join_token(ttl_s=600), public_key)
    writer.approve("dev-a")
    snapshot = DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
    )
    writer.revoke("dev-a")
    assert snapshot.device_public_key("dev-a") == public_key  # stale by design
