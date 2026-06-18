"""Test-only Ed25519 device-identity helpers (ADR-0016 / Step S3).

The device-identity path is asymmetric: a device generates an Ed25519 keypair,
keeps the private key, and registers only the base64 public key. These helpers
let the suite play the device side — generate a keypair, hand the public key to
the store, and self-sign EdDSA JWTs with the private key — without any real
randomness or real time (the keypair is derived from a fixed seed so a given
``seed`` always yields the same key; CLAUDE.md §11 hermetic).

None of these keys are credentials: they are derived from obvious in-repo seed
constants and exist only to exercise the verifier. Real devices generate their
keypair on-device and never share the private key.
"""

from __future__ import annotations

import base64
import datetime as _dt

import jwt  # PyJWT
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

#: EdDSA over Ed25519 — the algorithm a device self-signs with (ADR-0016 §2).
DEVICE_ALGO = "EdDSA"
TEST_ISSUER = "bardllm-pro"


def device_keypair(seed: bytes) -> tuple[Ed25519PrivateKey, str]:
    """A deterministic Ed25519 keypair for a test device.

    ``seed`` MUST be 32 bytes; the same seed always yields the same keypair, so
    the suite is reproducible. Returns ``(private_key, public_key_b64)`` where
    the public key is the standard-base64 32-byte encoding the device registers.
    """
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    raw_public = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_key, base64.b64encode(raw_public).decode("ascii")


def seed_for(label: str) -> bytes:
    """A 32-byte seed derived from a human label, so each test device gets a
    distinct, stable keypair (e.g. ``seed_for("dev-a")``)."""
    raw = label.encode("utf-8")
    return (raw + b"\x00" * 32)[:32]


def keypair_for(label: str) -> tuple[Ed25519PrivateKey, str]:
    """Convenience: a deterministic keypair keyed by a human label."""
    return device_keypair(seed_for(label))


def public_key_b64_for(label: str) -> str:
    """Just the base64 public key for a label (when the test only registers)."""
    return keypair_for(label)[1]


def mint_device_token(
    device_id: str,
    private_key: Ed25519PrivateKey,
    *,
    issuer: str = TEST_ISSUER,
    ttl_s: float = 3600.0,
    now: _dt.datetime | None = None,
) -> str:
    """Self-sign a per-device EdDSA JWT (sub=deviceId, iss, exp) with the device's
    PRIVATE key — the device side of the asymmetric contract. ``now`` defaults to
    real UTC; tests pass a fake clock's value for determinism."""
    issued = now if now is not None else _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {
            "sub": device_id,
            "iss": issuer,
            "iat": issued,
            "exp": issued + _dt.timedelta(seconds=ttl_s),
        },
        private_key,
        algorithm=DEVICE_ALGO,
    )
