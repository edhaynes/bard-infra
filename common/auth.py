"""Token verification, behind an interface.

The MVP verifies a JWT in ``Request.metadata.authToken`` (FR-2). The
``TokenVerifier`` protocol exists so the post-MVP PQ-identity verifier
(TRUST_MODEL.md §10) can replace ``JwtVerifier`` without touching call sites.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import jwt

from common.config import Config


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or untrusted."""


@runtime_checkable
class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict:
        """Return claims on success; raise :class:`AuthError` otherwise."""
        ...


@runtime_checkable
class TokenMinter(Protocol):
    def token(self) -> str:
        """Return a freshly-minted, short-lived bearer token for an internal,
        service-to-service call. The contract is intentionally argument-free:
        callers ask for "a token that authenticates ME as the service," not a
        token for some subject they choose."""
        ...


class JwtVerifier:
    """HMAC JWT verifier. Secret is injected — never read from a global."""

    def __init__(self, secret: str, algorithm: str = "HS256", issuer: str | None = None):
        if not secret:
            raise ValueError("JWT secret is required")
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer

    @classmethod
    def from_config(cls, config: Config) -> JwtVerifier:
        config.require("jwt_secret")
        return cls(config.jwt_secret, config.jwt_algorithm, config.jwt_issuer)

    def verify(self, token: str) -> dict:
        # Require exp/iss/sub and validate expiry (finding M-1): without an
        # explicit ``require`` PyJWT only validates ``exp`` when present, so a
        # token minted with no ``exp`` would never expire. ``leeway`` absorbs
        # small clock skew between the minter and the verifier.
        kwargs: dict = {
            "algorithms": [self._algorithm],
            "leeway": 30,
            "options": {"require": ["exp", "iss", "sub"], "verify_exp": True},
        }
        if self._issuer:
            kwargs["issuer"] = self._issuer
        try:
            return jwt.decode(token, self._secret, **kwargs)
        except jwt.PyJWTError as exc:
            raise AuthError(str(exc)) from exc


class FleetTokenMinter:
    """Mint short-lived fleet JWTs for the Router's OWN internal calls (bug #63).

    The Router holds the fleet ``BARDPRO_JWT_SECRET`` (it builds a
    :class:`JwtVerifier` from it), so it can authenticate to the Registry as a
    *service*, signing with that secret, rather than forwarding the caller's
    credential. This is what lets a per-device caller reach the data path: the
    caller's per-device token authorizes ``POST /v1/message``, while the
    Router's own fleet token authorizes the internal ``GET /agents/{id}`` lookup
    the Registry gates fleet-only. Smallest blast radius — the Registry stays
    fleet-only and unchanged.

    The minted token mirrors the fleet credential shape (``sub``/``iss``/``exp``)
    so :class:`JwtVerifier` accepts it with no special-casing. ``subject`` names
    the service principal (audit/debug clarity), defaulting to ``"bard-router"``.
    """

    def __init__(
        self,
        secret: str,
        *,
        algorithm: str = "HS256",
        issuer: str | None = None,
        subject: str = "bard-router",
        ttl_s: float = 60.0,
        clock: Callable[[], _dt.datetime] | None = None,
    ):
        if not secret:
            raise ValueError("JWT secret is required")
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._subject = subject
        self._ttl_s = ttl_s
        # Injectable clock for deterministic tests; defaults to real UTC now.
        self._now = clock or (lambda: _dt.datetime.now(_dt.UTC))

    @classmethod
    def from_config(cls, config: Config, *, subject: str = "bard-router") -> FleetTokenMinter:
        config.require("jwt_secret")
        return cls(
            config.jwt_secret,
            algorithm=config.jwt_algorithm,
            issuer=config.jwt_issuer,
            subject=subject,
        )

    def token(self) -> str:
        now = self._now()
        payload: dict = {
            "sub": self._subject,
            "iat": now,
            "exp": now + _dt.timedelta(seconds=self._ttl_s),
        }
        if self._issuer:
            payload["iss"] = self._issuer
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)
