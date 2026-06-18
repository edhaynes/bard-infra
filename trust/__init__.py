"""Zero-trust workgroup join harness (TRUST_MODEL.md).

LEVEL 0: validates the *join state machine* — identity → attestation →
join request → manager approval (device-approval gate) → MLS-style group
re-key → epoch-key delivery → send → revoke → lock-out — using STUB crypto.

LEVEL 1 (future): swap the stub Identity/GroupSession for hybrid PQ keys
(Ed25519+ML-DSA) and a real OpenMLS group behind these same interfaces. The
test in tests/test_trust_join.py should pass unchanged.
"""
