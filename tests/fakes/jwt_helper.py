"""Test-only JWT helpers.

The secret below is a non-secret placeholder used solely by the test suite.
Real deployments supply ``BARDPRO_JWT_SECRET`` via config (CLAUDE.md §3 — never
hardcode a real secret). Lanes verifying JWTs should accept an injected secret
so production keys never touch the codebase.
"""

from __future__ import annotations

import datetime as _dt

import jwt  # PyJWT

# Obvious placeholder — NOT a real credential. >=32 bytes only to satisfy the
# HMAC length check; the value is intentionally non-secret.
TEST_JWT_SECRET = "test-only-not-a-secret-padding-0123456789"  # noqa: S105
TEST_ALGO = "HS256"
TEST_ISSUER = "bardllm-pro"


def mint_test_token(
    subject: str = "test-user",
    ttl_seconds: int = 3600,
    secret: str = TEST_JWT_SECRET,
) -> str:
    now = _dt.datetime.now(_dt.UTC)
    payload = {
        "sub": subject,
        "iss": TEST_ISSUER,
        "iat": now,
        "exp": now + _dt.timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm=TEST_ALGO)


def verify_test_token(token: str, secret: str = TEST_JWT_SECRET) -> dict:
    return jwt.decode(token, secret, algorithms=[TEST_ALGO], issuer=TEST_ISSUER)
