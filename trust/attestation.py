"""Element 2 — device attestation (the basis for manager approval).

LEVEL 0 stub: an evidence string. LEVEL 1: a Secure Enclave / TPM 2.0 quote
proving the identity key is non-exportable and the device is genuine.
"""

from __future__ import annotations

from dataclasses import dataclass

from trust.identity import Identity


@dataclass(frozen=True)
class Attestation:
    device_id: str
    identity_pubkey: str
    evidence: str  # "valid" | "invalid" (stub)


def attest(identity: Identity, device_id: str = "dev-0", valid: bool = True) -> Attestation:
    return Attestation(device_id, identity.public_key, "valid" if valid else "invalid")


def verify_attestation(att: Attestation) -> bool:
    # LEVEL 1: verify the hardware quote chain.
    return att.evidence == "valid"
