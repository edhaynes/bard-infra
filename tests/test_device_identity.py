"""Sprint B2 — per-device identity, contract-first (ADR-0010, pragmatic JWT-class).

Tests are written against ``contracts/enrollment.schema.json`` BEFORE the
implementation (CLAUDE.md §11). They pin the enrollment state machine
(join-token -> pending -> active -> revoked), per-device key isolation (a token
minted for device A is rejected when presented as device B), and rejection of
unknown / not-yet-approved / revoked devices.

No network, no real clock, no real time: the ``DeviceStore`` takes an injectable
clock and deterministic id/secret generators so the suite is hermetic.
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
    InvalidStateTransition,
)

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


def _seq_secrets():
    """Deterministic per-device secret generator (>=32 bytes each)."""
    n = 0

    def _gen() -> str:
        nonlocal n
        n += 1
        return f"device-secret-{n:02d}-padding-0123456789-abcdef"

    return _gen


def _store(tmp_path: Path, clock: FakeClock) -> DeviceStore:
    return DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
        secret_factory=_seq_secrets(),
    )


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
    record = store.enroll("dev-a", jt, label="Alice's laptop")
    _contract_validator("DeviceRecord").validate(record)
    assert record["state"] == "pending"
    assert record["deviceId"] == "dev-a"
    assert record["label"] == "Alice's laptop"
    # The per-device secret is NEVER part of the persisted/returned record.
    assert "deviceSecret" not in record


def test_approve_response_matches_contract(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    record, secret = store.approve("dev-a")
    _contract_validator("ApproveResponse").validate({"device": record, "deviceSecret": secret})
    assert record["state"] == "active"
    assert len(secret.encode()) >= 32


# --- enrollment state machine ------------------------------------------------


def test_full_lifecycle_join_pending_active_then_mint_and_verify(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)

    jt = store.issue_join_token(ttl_s=600)
    pending = store.enroll("dev-a", jt)
    assert pending["state"] == "pending"

    record, secret = store.approve("dev-a")
    assert record["state"] == "active"

    token = store.mint_device_token("dev-a", secret, ttl_s=3600)
    claims = verifier.verify(token)
    assert claims["sub"] == "dev-a"


def test_revoked_device_verify_fails(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)

    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    _, secret = store.approve("dev-a")
    token = store.mint_device_token("dev-a", secret, ttl_s=3600)
    # Valid while active.
    verifier.verify(token)

    store.revoke("dev-a")
    assert store.get_device("dev-a")["state"] == "revoked"
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_pending_device_cannot_verify(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    # A pending device has no secret yet; even a guessed/forged token is rejected
    # because the device is not active. Sign with the join secret as the attacker
    # would have nothing better.
    forged = store.mint_device_token("dev-a", JOIN_SECRET, ttl_s=3600)
    with pytest.raises(AuthError):
        verifier.verify(forged)


def test_approve_requires_pending(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
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


# --- join-token validation ---------------------------------------------------


def test_enroll_rejects_bad_join_token(tmp_path):
    store = _store(tmp_path, FakeClock())
    with pytest.raises(InvalidJoinToken):
        store.enroll("dev-a", "not-a-valid-join-token")


def test_enroll_rejects_expired_join_token(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=60)
    clock.advance(120)
    with pytest.raises(InvalidJoinToken):
        store.enroll("dev-a", jt)


def test_enroll_duplicate_device_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt1 = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt1)
    jt2 = store.issue_join_token(ttl_s=600)
    with pytest.raises(InvalidStateTransition):
        store.enroll("dev-a", jt2)


# --- per-device key isolation ------------------------------------------------


def test_token_for_a_rejected_as_b(tmp_path):
    """A token minted with device A's secret but carrying sub=dev-b must be
    rejected: B's stored secret won't verify A's signature."""
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)

    for dev in ("dev-a", "dev-b"):
        jt = store.issue_join_token(ttl_s=600)
        store.enroll(dev, jt)
    _, secret_a = store.approve("dev-a")
    store.approve("dev-b")

    # Sign with A's secret but claim to be B.
    cross = store.mint_device_token("dev-b", secret_a, ttl_s=3600)
    with pytest.raises(AuthError):
        verifier.verify(cross)


def test_each_device_gets_a_distinct_secret(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    for dev in ("dev-a", "dev-b"):
        jt = store.issue_join_token(ttl_s=600)
        store.enroll(dev, jt)
    _, secret_a = store.approve("dev-a")
    _, secret_b = store.approve("dev-b")
    assert secret_a != secret_b


# --- unknown device rejected -------------------------------------------------


def test_unknown_device_token_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    # A token for a deviceId that was never enrolled.
    token = store.mint_device_token("ghost", JOIN_SECRET, ttl_s=3600)
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_token_without_sub_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    import jwt  # PyJWT

    now = clock()
    bad = jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        JOIN_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        verifier.verify(bad)


def test_token_malformed_rejected(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    with pytest.raises(AuthError):
        verifier.verify("not.a.jwt")


# --- persistence round-trip --------------------------------------------------


def test_store_persists_and_reloads(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    _, secret = store.approve("dev-a")

    # A fresh store over the same file sees the active device and its secret.
    reloaded = DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
        secret_factory=_seq_secrets(),
    )
    assert reloaded.get_device("dev-a")["state"] == "active"
    verifier = PerDeviceVerifier(reloaded, issuer=ISSUER, clock=clock)
    token = reloaded.mint_device_token("dev-a", secret, ttl_s=3600)
    assert verifier.verify(token)["sub"] == "dev-a"


def test_list_devices(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    listing = store.list_devices()
    assert len(listing) == 1
    _contract_validator("DeviceList").validate(listing)


def test_store_without_path_does_not_persist(tmp_path):
    store = DeviceStore(
        None,
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=FakeClock(),
        secret_factory=_seq_secrets(),
    )
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    assert store.get_device("dev-a")["state"] == "pending"


# --- guard branches ----------------------------------------------------------


def test_device_store_requires_join_secret(tmp_path):
    with pytest.raises(ValueError, match="join_token_secret is required"):
        DeviceStore(None, join_token_secret="", issuer=ISSUER)


def test_verifier_uses_real_clock_when_none(tmp_path):
    """With no injected clock, exp is validated against real UTC (production
    path). A token minted just now (real time) verifies; an already-expired one
    is rejected by PyJWT's own verify_exp."""
    store = DeviceStore(tmp_path / "devices.json", join_token_secret=JOIN_SECRET, issuer=ISSUER)
    jt = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", jt)
    _, secret = store.approve("dev-a")
    verifier = PerDeviceVerifier(store, issuer=ISSUER)  # clock=None
    token = store.mint_device_token("dev-a", secret, ttl_s=3600)
    assert verifier.verify(token)["sub"] == "dev-a"

    expired = store.mint_device_token("dev-a", secret, ttl_s=-3600)
    with pytest.raises(AuthError):
        verifier.verify(expired)


def test_verifier_injected_clock_detects_expiry(tmp_path):
    """With an injected clock, an exp earlier than the clock's now is rejected
    by our own check (covers the clock-present expiry branch)."""
    clock = FakeClock()
    store = _store(tmp_path, clock)
    _, secret = store.approve(_enrolled(store, "dev-a"))
    verifier = PerDeviceVerifier(store, issuer=ISSUER, clock=clock)
    token = store.mint_device_token("dev-a", secret, ttl_s=60)
    verifier.verify(token)  # valid now
    clock.advance(120)  # advance past exp
    with pytest.raises(AuthError):
        verifier.verify(token)


def _enrolled(store, device_id):
    store.enroll(device_id, store.issue_join_token(ttl_s=600))
    return device_id


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
    _, secret = store.approve(_enrolled(store, "dev-a"))
    token = store.mint_device_token("dev-a", secret, ttl_s=3600)
    # Fails the fleet verifier (wrong key), passes the per-device verifier.
    assert composite.verify(token)["sub"] == "dev-a"


def test_fleet_or_device_rejects_token_failing_both(tmp_path):
    clock = FakeClock()
    composite, store, _ = _fleet_or_device(tmp_path, clock)
    _, secret = store.approve(_enrolled(store, "dev-a"))
    token = store.mint_device_token("dev-a", secret, ttl_s=3600)
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
    _, secret = writer.approve(_enrolled(writer, "dev-a"))
    assert reader.device_secret("dev-a") == secret  # approve visible

    writer.revoke("dev-a")
    assert reader.device_secret("dev-a") is None  # revoke visible, no restart


def test_snapshot_store_misses_cross_instance_revoke(tmp_path):
    """The default (reload_on_read=False) is a boot-time snapshot — pinning WHY
    the Router must opt in: without reload, a Registry-side revoke would keep
    verifying until restart."""
    clock = FakeClock()
    writer = _store(tmp_path, clock)
    _, secret = writer.approve(_enrolled(writer, "dev-a"))
    snapshot = DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
    )
    writer.revoke("dev-a")
    assert snapshot.device_secret("dev-a") == secret  # stale by design
