"""Zero-knowledge seed-escrow store (ADR-0016 / Step S7 — recovery).

The MVP recovery answer to ADR-0009's open "user-key recovery ceremony" item.
A device's Ed25519 identity is derived from a 256-bit **seed**. The CLIENT wraps
that seed TWICE — once under an Argon2id key from the user's app password, and
once under a one-time OMG code — and uploads the two CIPHERTEXTS keyed by a
lightweight account handle (email / username). This store persists **only the
opaque ciphertext** and the device's public key. It can NEVER decrypt the seed:
the wrapping keys (the password / OMG code) never reach the server, so the
escrow is "hardware-backup-token"-class recovery, not server custody of keys
(ADR-0016 Reconciliation (b)).

What the server stores vs. what it never sees:

  - STORES: handle -> {publicKey, wraps:{password, omg}, createdAt, updatedAt}.
    ``wraps.*`` are treated as opaque base64 blobs — this store NEVER parses,
    base64-decodes, or interprets them; it round-trips the strings verbatim.
  - NEVER SEES: the 32-byte seed, the app password, the OMG code, or the
    Argon2id-derived wrapping keys. None of those ever touch the server.

Persistence lives in its OWN JSON file, parallel to (never merged into) the
DeviceStore / ChannelStore / agent state files — the same "separate file per
concern" rule those stores follow, so each persisted shape stays a stable
contract. The clock is injected so the unit suite is hermetic (no real time;
CLAUDE.md §11). ``reload_on_read`` re-reads the backing file before a lookup so
a record written by a concurrent writer (a second process) is visible — the
same read-replica seam DeviceStore/ChannelStore use.

The state file holds only ciphertext, but it is treated as sensitive and
gitignored (``recovery-state.json*``).
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from registry.device_store import _validate_public_key


class HandleConflict(ValueError):
    """Raised when a handle is already claimed by a DIFFERENT public key (409).

    The handle binds to the FIRST device's public key; a different key for the
    same handle would let one identity overwrite another's escrow, so it is
    rejected. The same key re-uploading is idempotent (OMG rotation), not a
    conflict."""


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class RecoveryStore:
    """JSON-persisted zero-knowledge escrow records, keyed by account handle.

    Persisted shape (its own file)::

        {handle: {"handle": str,
                  "publicKey": <base64>,
                  "wraps": {"password": <base64>, "omg": <base64>},
                  "createdAt": <iso>,
                  "updatedAt": <iso>}}

    ``wraps.*`` are opaque base64 ciphertext: the store round-trips them and
    never decrypts. Only ``publicKey`` is validated (it must be a real 32-byte
    Ed25519 key, reusing the DeviceStore validator) — the wraps are not the
    server's to interpret.
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        clock: Callable[[], _dt.datetime] | None = None,
        reload_on_read: bool = False,
    ):
        self._path = Path(state_path) if state_path else None
        self._clock = clock or _utcnow
        # When a separate recovering process reads while the enrolling process
        # writes, ``reload_on_read`` re-reads the file before a lookup so the
        # freshly-stored record is visible — the same read-replica seam the
        # DeviceStore/ChannelStore use for cross-process propagation.
        self._reload_on_read = reload_on_read
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    # --- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self._path and self._path.is_file():
            self._records = json.loads(self._path.read_text(encoding="utf-8"))

    def save(self) -> None:
        if self._path:
            self._path.write_text(json.dumps(self._records, indent=2), encoding="utf-8")

    # --- escrow --------------------------------------------------------------

    def store(
        self,
        handle: str,
        public_key: str,
        password_wrap: str,
        omg_wrap: str,
    ) -> dict[str, Any]:
        """Bind ``handle`` -> ``public_key`` and escrow the two opaque ciphertext
        wraps. Validates the public key first (fail fast — a malformed key is
        rejected, never persisted). Idempotent for the SAME public key: a repeat
        store overwrites the wraps (this is how OMG rotation re-escrows a fresh
        OMG-wrapped seed) and refreshes ``updatedAt`` while keeping the original
        ``createdAt``. A DIFFERENT public key for an existing handle raises
        :class:`HandleConflict` (409) — the handle is owned by its first key.

        ``password_wrap`` / ``omg_wrap`` are stored VERBATIM as opaque base64;
        this method never decodes or interprets them — the server cannot decrypt
        the seed.
        """
        public_key = _validate_public_key(public_key)
        now_iso = self._clock().isoformat()
        existing = self._records.get(handle)
        if existing is not None:
            if existing["publicKey"] != public_key:
                raise HandleConflict(
                    f"handle {handle!r} is already claimed by a different public key"
                )
            existing["wraps"] = {"password": password_wrap, "omg": omg_wrap}
            existing["updatedAt"] = now_iso
            self.save()
            return dict(existing)
        record: dict[str, Any] = {
            "handle": handle,
            "publicKey": public_key,
            "wraps": {"password": password_wrap, "omg": omg_wrap},
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        self._records[handle] = record
        self.save()
        return dict(record)

    # --- reads ---------------------------------------------------------------

    def get(self, handle: str) -> dict[str, Any] | None:
        """The escrowed ``{publicKey, wraps:{password, omg}}`` for ``handle``, or
        ``None`` when the handle is unknown (the HTTP layer maps that to 404).

        Returns the ciphertext only — useless without the password / OMG code,
        which the server never holds. A recovering device has no token yet, so
        the calling endpoint is unauthenticated; this read carries no secret to
        leak (the wraps are opaque and undecryptable without the user's key).
        """
        if self._reload_on_read:
            self._load()
        record = self._records.get(handle)
        if record is None:
            return None
        return {"publicKey": record["publicKey"], "wraps": dict(record["wraps"])}
