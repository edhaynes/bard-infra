"""Element 1 — per-entity identity + its MLS KeyPackage.

LEVEL 0 stub: a random keypair stand-in. LEVEL 1: hybrid Ed25519 + ML-DSA-65 in
a hardware-backed, non-exportable store (Secure Enclave / TPM / StrongBox).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyPackage:
    """What a client publishes to request joining a group (MLS KeyPackage)."""

    identity_pubkey: str
    init_key: str


@dataclass(frozen=True)
class Identity:
    name: str
    public_key: str
    _private: str

    @classmethod
    def generate(cls, name: str) -> Identity:
        priv = secrets.token_hex(16)
        pub = hashlib.sha256(priv.encode()).hexdigest()[:16]
        return cls(name=name, public_key=pub, _private=priv)

    def sign(self, data: bytes) -> str:
        # STUB. Level 1: hybrid Ed25519 + ML-DSA signature for attribution.
        return hashlib.sha256(self._private.encode() + data).hexdigest()

    def key_package(self) -> KeyPackage:
        return KeyPackage(identity_pubkey=self.public_key, init_key=secrets.token_hex(8))
