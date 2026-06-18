"""Step S7 — zero-knowledge seed-escrow store unit tests (ADR-0016 §5).

Tests are written against the FROZEN contract (contracts/recovery.schema.json)
and pin the store's behaviour BEFORE the HTTP layer (CLAUDE.md §11): store /
overwrite (OMG rotation) / conflict, persistence + ``reload_on_read``
propagation, and — the headline guarantee — that the store NEVER needs or uses
the plaintext seed (it round-trips opaque ciphertext verbatim and cannot
decrypt). Hermetic: injected clock, tmp-file persistence, no network, no real
keys (deterministic placeholder Ed25519 public keys from the ed25519 helper).
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
from pathlib import Path

import pytest

from registry.device_store import InvalidPublicKey
from registry.recovery_store import HandleConflict, RecoveryStore
from tests.fakes.ed25519_helper import public_key_b64_for


class FakeClock:
    """Deterministic clock (no sleeping) — mirrors the device-store suite."""

    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 6, 18, 12, 0, 0, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


# Opaque ciphertext placeholders — NOT real wraps; the server never decrypts
# them. Any base64-ish string would do; the store round-trips them verbatim.
PW_WRAP = base64.b64encode(b"password-wrapped-seed-ciphertext").decode("ascii")
OMG_WRAP = base64.b64encode(b"omg-code-wrapped-seed-ciphertext").decode("ascii")
PW_WRAP_2 = base64.b64encode(b"rotated-password-wrap-ciphertext").decode("ascii")
OMG_WRAP_2 = base64.b64encode(b"rotated-omg-wrap-ciphertext-here").decode("ascii")


def _store(tmp_path: Path | None = None, clock: FakeClock | None = None, **kw) -> RecoveryStore:
    path = (tmp_path / "recovery-state.json") if tmp_path is not None else None
    return RecoveryStore(path, clock=clock or FakeClock(), **kw)


# --- store (create) ----------------------------------------------------------


def test_store_creates_record_with_timestamps():
    clock = FakeClock()
    store = _store(clock=clock)
    rec = store.store("alice@example.com", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    assert rec["handle"] == "alice@example.com"
    assert rec["publicKey"] == public_key_b64_for("phone-1")
    assert rec["wraps"] == {"password": PW_WRAP, "omg": OMG_WRAP}
    assert rec["createdAt"] == clock.now.isoformat()
    assert rec["updatedAt"] == clock.now.isoformat()


def test_store_rejects_malformed_public_key():
    store = _store()
    with pytest.raises(InvalidPublicKey):
        store.store("alice", "not-base64-!!", PW_WRAP, OMG_WRAP)
    # Nothing was persisted (fail fast before any write).
    assert store.get("alice") is None


def test_store_rejects_wrong_length_public_key():
    store = _store()
    short = base64.b64encode(b"too-short").decode("ascii")
    with pytest.raises(InvalidPublicKey):
        store.store("alice", short, PW_WRAP, OMG_WRAP)


# --- store (overwrite — OMG rotation) ----------------------------------------


def test_store_same_key_overwrites_wraps_and_refreshes_updated_at():
    clock = FakeClock()
    store = _store(clock=clock)
    pk = public_key_b64_for("phone-1")
    first = store.store("alice", pk, PW_WRAP, OMG_WRAP)
    clock.advance(60)
    again = store.store("alice", pk, PW_WRAP_2, OMG_WRAP_2)
    # OMG rotation: the wraps are replaced, createdAt stays, updatedAt moves.
    assert again["wraps"] == {"password": PW_WRAP_2, "omg": OMG_WRAP_2}
    assert again["createdAt"] == first["createdAt"]
    assert again["updatedAt"] != first["updatedAt"]
    assert again["updatedAt"] == clock.now.isoformat()
    # A single record (overwritten, not appended).
    assert store.get("alice")["wraps"]["omg"] == OMG_WRAP_2


# --- store (conflict) --------------------------------------------------------


def test_store_different_key_same_handle_conflicts():
    store = _store()
    store.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    with pytest.raises(HandleConflict):
        store.store("alice", public_key_b64_for("phone-2"), PW_WRAP_2, OMG_WRAP_2)
    # The original escrow is untouched by the rejected conflict.
    assert store.get("alice")["publicKey"] == public_key_b64_for("phone-1")
    assert store.get("alice")["wraps"] == {"password": PW_WRAP, "omg": OMG_WRAP}


def test_different_handles_are_independent():
    store = _store()
    store.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    store.store("bob", public_key_b64_for("phone-2"), PW_WRAP_2, OMG_WRAP_2)
    assert store.get("alice")["publicKey"] == public_key_b64_for("phone-1")
    assert store.get("bob")["publicKey"] == public_key_b64_for("phone-2")


# --- get ---------------------------------------------------------------------


def test_get_unknown_handle_returns_none():
    assert _store().get("nobody") is None


def test_get_returns_ciphertext_only_no_internal_fields():
    store = _store()
    store.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    fetched = store.get("alice")
    # The fetch projection is exactly the contract's EscrowFetch — public key +
    # the two opaque wraps. No createdAt/updatedAt/handle leak into the read.
    assert set(fetched.keys()) == {"publicKey", "wraps"}
    assert fetched["wraps"] == {"password": PW_WRAP, "omg": OMG_WRAP}


def test_get_returns_a_copy_not_the_live_record():
    store = _store()
    store.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    fetched = store.get("alice")
    fetched["wraps"]["omg"] = "mutated"
    # Mutating the returned dict must not corrupt the stored record.
    assert store.get("alice")["wraps"]["omg"] == OMG_WRAP


# --- zero-knowledge: the store never needs/sees the plaintext -----------------


def test_store_never_decodes_or_interprets_the_wraps():
    """The headline guarantee: the wraps are opaque. A wrap that is NOT even
    valid base64 (let alone a decryptable ciphertext) is stored and returned
    verbatim — proving the server never parses, decodes, or decrypts it."""
    store = _store()
    opaque = "this-is-not-base64-and-the-server-does-not-care-!!!"
    store.store("alice", public_key_b64_for("phone-1"), opaque, opaque)
    assert store.get("alice")["wraps"] == {"password": opaque, "omg": opaque}


# --- persistence + reload_on_read --------------------------------------------


def test_persists_to_disk_and_reloads(tmp_path: Path):
    clock = FakeClock()
    s1 = _store(tmp_path, clock)
    s1.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    # A fresh store over the same file sees the persisted escrow.
    s2 = _store(tmp_path, clock)
    assert s2.get("alice")["wraps"] == {"password": PW_WRAP, "omg": OMG_WRAP}


def test_persisted_file_is_json_with_expected_shape(tmp_path: Path):
    store = _store(tmp_path)
    store.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    data = json.loads((tmp_path / "recovery-state.json").read_text())
    assert set(data["alice"].keys()) == {
        "handle",
        "publicKey",
        "wraps",
        "createdAt",
        "updatedAt",
    }


def test_reload_on_read_sees_concurrent_writer(tmp_path: Path):
    clock = FakeClock()
    writer = _store(tmp_path, clock)  # the enrolling process
    reader = _store(tmp_path, clock, reload_on_read=True)  # the recovering process
    # Reader has not seen it yet (nothing written before reader loaded).
    assert reader.get("alice") is None
    writer.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    # With reload_on_read the next get re-reads the file and sees the escrow.
    assert reader.get("alice")["publicKey"] == public_key_b64_for("phone-1")


def test_without_reload_on_read_does_not_see_concurrent_writer(tmp_path: Path):
    clock = FakeClock()
    writer = _store(tmp_path, clock)
    reader = _store(tmp_path, clock)  # reload_on_read defaults False
    writer.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    # Frozen at construction: the reader does not re-read, so it misses the write.
    assert reader.get("alice") is None


def test_pathless_store_does_not_persist():
    """state_path=None is the in-memory test mode — store works, save is a no-op."""
    store = RecoveryStore(None, clock=FakeClock())
    store.store("alice", public_key_b64_for("phone-1"), PW_WRAP, OMG_WRAP)
    assert store.get("alice")["publicKey"] == public_key_b64_for("phone-1")
