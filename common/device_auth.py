"""Per-device token verifier (Sprint B2 / ADR-0010; asymmetric upgrade ADR-0016/S3).

:class:`PerDeviceVerifier` implements the :class:`common.auth.TokenVerifier`
protocol, so it drops into the Router / Registry / broker call sites in place of
the fleet-wide :class:`common.auth.JwtVerifier` with no changes to those sites.

Where ``JwtVerifier`` validates every token against ONE shared fleet secret,
this resolves the signing key *per device*: it reads the unverified ``sub``
(the deviceId), looks that device's **public key** up in the store, builds an
Ed25519 public key from it, and only then verifies the device's self-signed
EdDSA signature with that key. ADR-0016/S3 completed the seam the original docs
anticipated: the symmetric per-device HMAC secret became a device-generated
Ed25519 public key, and the verify algorithm went HS256 -> EdDSA. The private
key never leaves the device, so the server can verify but never impersonate a
device (the H-2 single-shared-secret risk is gone on the device path).

Security properties pinned by tests/test_device_identity.py and
tests/test_security_pentest.py:
  - unknown / unenrolled deviceId  -> AuthError (no key to verify against)
  - pending (not-yet-approved)      -> AuthError (store yields no public key)
  - revoked                         -> AuthError (public key wiped on revoke)
  - token for A presented as B      -> AuthError (B's key won't verify A's sig)
  - HS256 / non-EdDSA token         -> AuthError (algorithm not allowed)
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
from collections.abc import Callable

import jwt  # PyJWT
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from common.auth import AuthError, TokenVerifier
from registry.device_store import DeviceStore

#: Devices self-sign EdDSA over their Ed25519 keypair; only EdDSA is accepted,
#: so an HS256 token (the retired symmetric credential, or an attacker trying to
#: pass the public key off as an HMAC secret) is rejected at the algorithm gate.
_ALGO = "EdDSA"


class FleetOrDeviceVerifier:
    """Opt-in coexistence verifier (Sprint B4 / bug #56 relay auth).

    Accepts EITHER a fleet JWT (the v1.x shared-secret credential) OR a
    per-device token (B2 enrollment / B3 invite redemption), so a fleet that
    enables device identity migrates device-by-device with nothing breaking:
    legacy agents keep relaying on the fleet JWT while enrolled devices present
    their own credential and are individually revocable.

    Order: the fleet verifier is tried first (cheap single-key check, and a
    fleet token's ``sub`` is an agentId that the device store would reject
    anyway); on :class:`~common.auth.AuthError` the per-device verifier decides.
    A token failing BOTH raises the per-device error, which names the device
    state (unknown / not active) — the more actionable diagnosis.

    Implements the :class:`common.auth.TokenVerifier` protocol, so it drops
    into the Router / broker call sites unchanged.
    """

    def __init__(self, fleet: TokenVerifier, device: TokenVerifier):
        self._fleet = fleet
        self._device = device

    def verify(self, token: str) -> dict:
        try:
            return self._fleet.verify(token)
        except AuthError:
            return self._device.verify(token)


class PerDeviceVerifier:
    """Resolve the device's public key by ``sub`` from the store, then verify the
    device's self-signed EdDSA token against it."""

    def __init__(
        self,
        store: DeviceStore,
        *,
        issuer: str,
        clock: Callable[[], _dt.datetime] | None = None,
    ):
        self._store = store
        self._issuer = issuer
        # When a clock is injected, expiry is checked against it (deterministic
        # tests); otherwise PyJWT validates exp against real UTC (production).
        self._clock = clock

    def verify(self, token: str) -> dict:
        # Read the claimed identity WITHOUT trusting the signature, so we know
        # which device's key to verify against. An unsigned read can be forged,
        # which is exactly why the signed verify below is the real gate.
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise AuthError(str(exc)) from exc

        device_id = unverified.get("sub")
        if not device_id:
            raise AuthError("token missing sub (deviceId)")

        public_key_b64 = self._store.device_public_key(device_id)
        if public_key_b64 is None:
            # Unknown, pending, or revoked device — no usable key.
            raise AuthError(f"device {device_id!r} is not active")

        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(public_key_b64, validate=True)
            )
        except (binascii.Error, ValueError) as exc:
            # A stored key is validated at registration, so this is defence in
            # depth: a corrupted record fails closed (no verification) rather
            # than crashing the request path.
            raise AuthError(f"stored public key for {device_id!r} is invalid: {exc}") from exc

        verify_exp = self._clock is None
        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=[_ALGO],
                issuer=self._issuer,
                leeway=30,
                options={"require": ["exp", "iss", "sub"], "verify_exp": verify_exp},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(str(exc)) from exc
        if self._clock is not None and claims["exp"] < self._clock().timestamp():
            raise AuthError("token has expired")
        return claims
