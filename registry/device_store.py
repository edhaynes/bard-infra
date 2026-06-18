"""Per-device identity store with JSON-file persistence (Sprint B2 / ADR-0010).

This is the v2 "software identity keys + JWT-class auth" enrollment lifecycle,
NOT the v3 hybrid-PQ/MLS trust fabric. Each device is issued its OWN signing
key (a per-device HMAC secret for v2; the :class:`PerDeviceVerifier` seam lets
an asymmetric / PQ credential slot in later) through the state machine frozen in
``contracts/enrollment.schema.json``::

    join-token -> (enroll)  -> pending
               -> (approve) -> active   (secret disclosed once)
               -> (revoke)  -> revoked  (verify fails thereafter)

Persistence lives in its OWN JSON file, parallel to (never merged into) the
agent ``RegistryStore`` state — the agent file is a flat ``{agentId: record}``
map that two liveness tests assert on directly, so devices get a separate file
to keep that contract intact. The per-device secret is held server-side (in
this file's persisted map) and is NEVER returned in a ``DeviceRecord``; it is
disclosed exactly once, at approval, to the manager.

The clock and the id/secret generators are injected so the unit suite is
hermetic — no real time, no real randomness (CLAUDE.md §2/§9, §11 no-network).
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jwt  # PyJWT

#: HMAC-SHA256 needs >= 32-byte keys (RFC 7518 §3.2 / bug #58). Per-device
#: secrets generated here clear that bar.
DEVICE_SECRET_BYTES = 32

STATE_PENDING = "pending"
STATE_ACTIVE = "active"
STATE_REVOKED = "revoked"

_ALGO = "HS256"
#: Marks a join token apart from a device token (a join token MUST NOT be usable
#: as a device credential — different audience).
_JOIN_AUDIENCE = "bard-device-enroll"


class DeviceNotFound(KeyError):
    """Raised when an unknown deviceId is looked up (maps to 404)."""


class InvalidJoinToken(ValueError):
    """Raised when a join token is missing, malformed, expired, or untrusted."""


class InvalidStateTransition(ValueError):
    """Raised on an illegal lifecycle move (e.g. approve a non-pending device)."""


#: Length of the derived workgroup-id suffix; trust.schema.yaml WorkgroupId
#: requires >=16 chars of [A-Za-z0-9_-] after the ``wg_`` prefix.
_WORKGROUP_ID_CHARS = 22


def derive_workgroup_id(name: str) -> str:
    """Deterministic v2 workgroup id from the group NAME (Sprint B6).

    The console assigns devices to groups by name; deriving the id as
    ``wg_`` + base64url(sha256(name)) (truncated) means equal names land in
    the same group across devices with no separate workgroup CRUD, and the
    result always matches ``trust.schema.yaml#/$defs/WorkgroupId``. v3's
    MLS-backed workgroups replace this derivation behind the same shape.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"wg_{encoded[:_WORKGROUP_ID_CHARS]}"


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _default_secret() -> str:
    return secrets.token_urlsafe(DEVICE_SECRET_BYTES)


class DeviceStore:
    """JSON-persisted per-device identity records + join-token issuance.

    The persisted map is ``{deviceId: {..record.., "secret": <hmac>}}``; the
    in-memory ``DeviceRecord`` views drop ``secret`` so it never leaves the
    process except via :meth:`approve`'s one-time return.
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        join_token_secret: str,
        issuer: str,
        clock: Callable[[], _dt.datetime] | None = None,
        secret_factory: Callable[[], str] | None = None,
        reload_on_read: bool = False,
    ):
        if not join_token_secret:
            raise ValueError("join_token_secret is required")
        self._path = Path(state_path) if state_path else None
        self._join_secret = join_token_secret
        self._issuer = issuer
        self._clock = clock or _utcnow
        self._secret_factory = secret_factory or _default_secret
        # Sprint B4 (relay auth / bug #56): a READ-side consumer in another
        # process (the Router's PerDeviceVerifier) shares this JSON file with
        # the writing Registry. With ``reload_on_read`` the key lookup re-reads
        # the file first, so an approve/revoke written by the Registry takes
        # effect at the Router on the next request — without it, a revoked
        # device would keep relaying until the Router restarts.
        self._reload_on_read = reload_on_read
        self._devices: dict[str, dict[str, Any]] = {}
        self._load()

    # --- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self._path and self._path.is_file():
            self._devices = json.loads(self._path.read_text(encoding="utf-8"))

    def save(self) -> None:
        if self._path:
            self._path.write_text(json.dumps(self._devices, indent=2), encoding="utf-8")

    # --- join tokens ---------------------------------------------------------

    def issue_join_token(self, *, ttl_s: float) -> str:
        """Mint a short-lived join token a device presents once at enroll."""
        now = self._clock()
        return jwt.encode(
            {
                "iss": self._issuer,
                "aud": _JOIN_AUDIENCE,
                "iat": now,
                "exp": now + _dt.timedelta(seconds=ttl_s),
            },
            self._join_secret,
            algorithm=_ALGO,
        )

    def _verify_join_token(self, token: str) -> None:
        # Signature, issuer, audience and required-claims are verified by PyJWT;
        # expiry is checked against the INJECTED clock (verify_exp disabled), so
        # tests advance a fake clock instead of waiting real seconds and the
        # whole lifecycle stays deterministic (§11 no-network/no-sleep).
        try:
            claims = jwt.decode(
                token,
                self._join_secret,
                algorithms=[_ALGO],
                audience=_JOIN_AUDIENCE,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"], "verify_exp": False},
            )
        except jwt.PyJWTError as exc:
            raise InvalidJoinToken(str(exc)) from exc
        if claims["exp"] < self._clock().timestamp():
            raise InvalidJoinToken("join token has expired")

    # --- lifecycle -----------------------------------------------------------

    def enroll(self, device_id: str, join_token: str, label: str | None = None) -> dict[str, Any]:
        """join-token -> pending. Validates the join token first (fail fast)."""
        self._verify_join_token(join_token)
        if device_id in self._devices:
            raise InvalidStateTransition(f"device {device_id!r} already enrolled")
        now_iso = self._clock().isoformat()
        record: dict[str, Any] = {
            "deviceId": device_id,
            "state": STATE_PENDING,
            "createdAt": now_iso,
        }
        if label is not None:
            record["label"] = label
        self._devices[device_id] = record
        self.save()
        return self._public(record)

    def approve(self, device_id: str) -> tuple[dict[str, Any], str]:
        """pending -> active. Generates and returns the per-device secret ONCE."""
        record = self._raw(device_id)
        if record["state"] != STATE_PENDING:
            raise InvalidStateTransition(
                f"device {device_id!r} is {record['state']!r}, not {STATE_PENDING!r}"
            )
        secret = self._secret_factory()
        record["state"] = STATE_ACTIVE
        record["approvedAt"] = self._clock().isoformat()
        record["secret"] = secret
        self.save()
        return self._public(record), secret

    def admit(self, device_id: str, label: str | None = None) -> tuple[dict[str, Any], str]:
        """Create a device directly ACTIVE, minting its secret in one step.

        This is the invite-redemption path (Sprint B3): the owner pre-authorized
        membership by sending the invite link, so there is no pending->approve
        gate — the device is admitted active immediately. Contrast :meth:`enroll`
        + :meth:`approve`, the fleet path that vets each node. Returns the public
        record and the freshly-minted per-device secret (one-time disclosure,
        same rule as :meth:`approve`). Rejects a deviceId that already exists, so
        a redeem cannot silently take over an enrolled/revoked device.
        """
        if device_id in self._devices:
            raise InvalidStateTransition(f"device {device_id!r} already exists")
        secret = self._secret_factory()
        now_iso = self._clock().isoformat()
        record: dict[str, Any] = {
            "deviceId": device_id,
            "state": STATE_ACTIVE,
            "createdAt": now_iso,
            "approvedAt": now_iso,
            "secret": secret,
        }
        if label is not None:
            record["label"] = label
        self._devices[device_id] = record
        self.save()
        return self._public(record), secret

    def revoke(self, device_id: str) -> dict[str, Any]:
        """-> revoked. Idempotent destination; the secret is wiped so a leaked
        copy can no longer be matched by the verifier even in memory."""
        record = self._raw(device_id)
        record["state"] = STATE_REVOKED
        record["revokedAt"] = self._clock().isoformat()
        record.pop("secret", None)
        self.save()
        return self._public(record)

    # --- console manage (Sprint B6 / feature #64) ------------------------------

    def rename(self, device_id: str, label: str) -> dict[str, Any]:
        """Set the device's human label (any lifecycle state; renaming a
        revoked device is harmless and keeps the history readable)."""
        record = self._raw(device_id)
        record["label"] = label
        self.save()
        return self._public(record)

    def assign_workgroup(self, device_id: str, name: str | None) -> dict[str, Any]:
        """Put the device in a workgroup by NAME, or take it out (``None``).

        Persists ``{"workgroupId": derive_workgroup_id(name), "name": name}``
        on the device record (contracts/enrollment.schema.json, B6 additive
        extension); ``GET /fleet`` surfaces it for console grouping.
        """
        record = self._raw(device_id)
        if name is None:
            record.pop("workgroup", None)
        else:
            record["workgroup"] = {"workgroupId": derive_workgroup_id(name), "name": name}
        self.save()
        return self._public(record)

    # --- reads ---------------------------------------------------------------

    def get_device(self, device_id: str) -> dict[str, Any]:
        return self._public(self._raw(device_id))

    def list_devices(self) -> list[dict[str, Any]]:
        return [self._public(r) for r in self._devices.values()]

    def device_secret(self, device_id: str) -> str | None:
        """The verifier seam's key lookup: the active device's HMAC secret, or
        None when the device is unknown or not active (pending/revoked)."""
        if self._reload_on_read:
            self._load()
        record = self._devices.get(device_id)
        if record is None or record["state"] != STATE_ACTIVE:
            return None
        return record.get("secret")

    # --- helpers -------------------------------------------------------------

    def mint_device_token(self, device_id: str, secret: str, *, ttl_s: float) -> str:
        """Mint a per-device JWT (sub=deviceId). Used by the agent path and the
        test suite; signing with the wrong secret is exactly the isolation case
        the verifier must reject."""
        now = self._clock()
        return jwt.encode(
            {
                "sub": device_id,
                "iss": self._issuer,
                "iat": now,
                "exp": now + _dt.timedelta(seconds=ttl_s),
            },
            secret,
            algorithm=_ALGO,
        )

    def _raw(self, device_id: str) -> dict[str, Any]:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise DeviceNotFound(device_id) from exc

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        """A DeviceRecord view with the server-held secret stripped."""
        return {k: v for k, v in record.items() if k != "secret"}
