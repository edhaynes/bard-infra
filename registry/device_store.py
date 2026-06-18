"""Per-device identity store with JSON-file persistence (Sprint B2 / ADR-0010,
upgraded to asymmetric identity for the MVP client tier in ADR-0016 / Step S3).

This is the v2 "software identity keys + JWT-class auth" enrollment lifecycle,
NOT the v3 hybrid-PQ/MLS trust fabric. Each device generates its OWN Ed25519
keypair on the device; the **private key never leaves the device**, and only the
**public key** is registered here. The device self-signs EdDSA JWTs and the
:class:`PerDeviceVerifier` verifies them against the stored public key. This
retires the symmetric, server-minted HMAC ``deviceSecret`` (ADR-0016 §3 — there
is no baked credential to leak or expire). The state machine frozen in
``contracts/enrollment.schema.json`` is unchanged::

    join-token -> (enroll)  -> pending   (public key registered)
               -> (approve) -> active    (verification enabled)
               -> (revoke)  -> revoked   (public key wiped; verify fails)

Persistence lives in its OWN JSON file, parallel to (never merged into) the
agent ``RegistryStore`` state — the agent file is a flat ``{agentId: record}``
map that two liveness tests assert on directly, so devices get a separate file
to keep that contract intact. The public key is, by definition, public: it is
stored on the record and surfaced in :meth:`_public` views (unlike the old HMAC
secret, which was server-held and never returned).

The clock is injected so the unit suite is hermetic — no real time (CLAUDE.md
§2/§9, §11 no-network). The device-supplied public key replaces the old
server-side secret generator: there is no per-device secret to mint here.
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jwt  # PyJWT

#: An Ed25519 public key is exactly 32 bytes (RFC 8032 §5.1.5). A registered
#: ``publicKey`` MUST base64-decode to this length, else it is malformed.
ED25519_PUBLIC_KEY_BYTES = 32

STATE_PENDING = "pending"
STATE_ACTIVE = "active"
STATE_REVOKED = "revoked"

#: Devices self-sign EdDSA (Ed25519) JWTs; join tokens stay HMAC (server-minted,
#: server-verified — the server holds the join secret, so symmetric is correct
#: there). Only the per-device credential goes asymmetric (ADR-0016 §2).
_JOIN_ALGO = "HS256"
#: Marks a join token apart from a device token (a join token MUST NOT be usable
#: as a device credential — different audience).
_JOIN_AUDIENCE = "bard-device-enroll"


class DeviceNotFound(KeyError):
    """Raised when an unknown deviceId is looked up (maps to 404)."""


class InvalidJoinToken(ValueError):
    """Raised when a join token is missing, malformed, expired, or untrusted."""


class InvalidStateTransition(ValueError):
    """Raised on an illegal lifecycle move (e.g. approve a non-pending device)."""


class InvalidPublicKey(ValueError):
    """Raised when a device-supplied public key is missing, not base64, or not a
    32-byte Ed25519 key. Maps to 400 at the HTTP layer (the client sent a bad
    key); caught at registration so a malformed key never reaches the store."""


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


def _validate_public_key(public_key: str) -> str:
    """Confirm ``public_key`` is base64 of a 32-byte Ed25519 key, returning it
    unchanged on success. Fail fast (§0.11): a malformed key is rejected at
    registration, never persisted, so the verifier never meets a bad key."""
    if not public_key:
        raise InvalidPublicKey("publicKey is required")
    try:
        raw = base64.b64decode(public_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidPublicKey(f"publicKey is not valid base64: {exc}") from exc
    if len(raw) != ED25519_PUBLIC_KEY_BYTES:
        raise InvalidPublicKey(
            f"publicKey must decode to {ED25519_PUBLIC_KEY_BYTES} bytes (Ed25519), got {len(raw)}"
        )
    return public_key


class DeviceStore:
    """JSON-persisted per-device identity records + join-token issuance.

    The persisted map is ``{deviceId: {..record.., "publicKey": <base64>}}``.
    The public key is, by design, surfaced in :meth:`_public` views — it is
    public material the device shares, not a secret to withhold.
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        join_token_secret: str,
        issuer: str,
        clock: Callable[[], _dt.datetime] | None = None,
        reload_on_read: bool = False,
    ):
        if not join_token_secret:
            raise ValueError("join_token_secret is required")
        self._path = Path(state_path) if state_path else None
        self._join_secret = join_token_secret
        self._issuer = issuer
        self._clock = clock or _utcnow
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
            algorithm=_JOIN_ALGO,
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
                algorithms=[_JOIN_ALGO],
                audience=_JOIN_AUDIENCE,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"], "verify_exp": False},
            )
        except jwt.PyJWTError as exc:
            raise InvalidJoinToken(str(exc)) from exc
        if claims["exp"] < self._clock().timestamp():
            raise InvalidJoinToken("join token has expired")

    # --- lifecycle -----------------------------------------------------------

    def enroll(
        self,
        device_id: str,
        join_token: str,
        public_key: str,
        label: str | None = None,
    ) -> dict[str, Any]:
        """join-token -> pending. Validates the join token AND the device's
        public key first (fail fast), then registers the public key."""
        self._verify_join_token(join_token)
        public_key = _validate_public_key(public_key)
        if device_id in self._devices:
            raise InvalidStateTransition(f"device {device_id!r} already enrolled")
        now_iso = self._clock().isoformat()
        record: dict[str, Any] = {
            "deviceId": device_id,
            "state": STATE_PENDING,
            "createdAt": now_iso,
            "publicKey": public_key,
        }
        if label is not None:
            record["label"] = label
        self._devices[device_id] = record
        self.save()
        return self._public(record)

    def approve(self, device_id: str) -> dict[str, Any]:
        """pending -> active. The device's public key was registered at enroll;
        approval simply enables verification (no secret to mint or disclose)."""
        record = self._raw(device_id)
        if record["state"] != STATE_PENDING:
            raise InvalidStateTransition(
                f"device {device_id!r} is {record['state']!r}, not {STATE_PENDING!r}"
            )
        record["state"] = STATE_ACTIVE
        record["approvedAt"] = self._clock().isoformat()
        self.save()
        return self._public(record)

    def admit(self, device_id: str, public_key: str, label: str | None = None) -> dict[str, Any]:
        """Create a device directly ACTIVE, registering its public key in one step.

        This is the invite-redemption path (Sprint B3): the owner pre-authorized
        membership by sending the invite link, so there is no pending->approve
        gate — the device is admitted active immediately with the public key it
        generated on-device. Contrast :meth:`enroll` + :meth:`approve`, the fleet
        path that vets each node. Rejects a deviceId that already exists, so a
        redeem cannot silently take over an enrolled/revoked device. Validates
        the public key first (fail fast) so a bad key is never persisted.
        """
        public_key = _validate_public_key(public_key)
        if device_id in self._devices:
            raise InvalidStateTransition(f"device {device_id!r} already exists")
        now_iso = self._clock().isoformat()
        record: dict[str, Any] = {
            "deviceId": device_id,
            "state": STATE_ACTIVE,
            "createdAt": now_iso,
            "approvedAt": now_iso,
            "publicKey": public_key,
        }
        if label is not None:
            record["label"] = label
        self._devices[device_id] = record
        self.save()
        return self._public(record)

    def self_register(
        self, device_id: str, public_key: str, label: str | None = None
    ) -> dict[str, Any]:
        """Owner-bootstrap registration (ADR-0016 / Step S5): create a device
        directly ACTIVE with NO invite and NO manager approval — the device that
        will create and own a box.

        Idempotent for the same ``deviceId`` + ``publicKey``: re-registering with
        the identical key returns the existing record (a retry is harmless). If
        the deviceId already exists with a DIFFERENT public key, raises
        :class:`InvalidStateTransition` (HTTP 409) so a self-register can never
        silently take over (or re-key) an existing device. Validates the public
        key first (fail fast) so a malformed key is never persisted.

        This is an OPEN, unauthenticated endpoint at the HTTP layer — the
        bootstrap has no prior credential to present — so it is the one path that
        admits a device active without a join token or invite.
        """
        public_key = _validate_public_key(public_key)
        existing = self._devices.get(device_id)
        if existing is not None:
            if existing.get("publicKey") == public_key:
                return self._public(existing)
            raise InvalidStateTransition(
                f"device {device_id!r} already exists with a different public key"
            )
        now_iso = self._clock().isoformat()
        record: dict[str, Any] = {
            "deviceId": device_id,
            "state": STATE_ACTIVE,
            "createdAt": now_iso,
            "approvedAt": now_iso,
            "publicKey": public_key,
        }
        if label is not None:
            record["label"] = label
        self._devices[device_id] = record
        self.save()
        return self._public(record)

    def revoke(self, device_id: str) -> dict[str, Any]:
        """-> revoked. Idempotent destination; the public key is wiped so the
        device's self-signed tokens stop verifying (there is no key to verify
        against), even before the state check would reject them."""
        record = self._raw(device_id)
        record["state"] = STATE_REVOKED
        record["revokedAt"] = self._clock().isoformat()
        record.pop("publicKey", None)
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

    def device_public_key(self, device_id: str) -> str | None:
        """The verifier seam's key lookup: the active device's base64 Ed25519
        public key, or None when the device is unknown or not active
        (pending/revoked, the latter having had its key wiped)."""
        if self._reload_on_read:
            self._load()
        record = self._devices.get(device_id)
        if record is None or record["state"] != STATE_ACTIVE:
            return None
        return record.get("publicKey")

    # --- helpers -------------------------------------------------------------

    def _raw(self, device_id: str) -> dict[str, Any]:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise DeviceNotFound(device_id) from exc

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        """A DeviceRecord view. The public key is public material, so — unlike
        the retired HMAC secret — it is surfaced rather than stripped; the view
        is a copy of the full record (no server-held secret remains to hide)."""
        return dict(record)
