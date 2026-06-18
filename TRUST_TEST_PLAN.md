Status: Partial — Level 0 join harness + test implemented (2026-06-08); Level 1 (real PQ + OpenMLS) pending

# Trust Test Plan — "a client connects to the zero-trust net"

Companion to `TRUST_MODEL.md`. Defines the canonical onboarding test, the
elements it needs, and a two-level plan so the test runs **today** (state
machine) and again **later** (real crypto) without changing.

## The workflow under test (client join → use → revoke)

```
 1. Bootstrap     client generates identity keypair (HW-backed); makes a KeyPackage
 2. Attest        device produces an attestation (key non-exportable, device genuine)
 3. Join request  client → manager: {attestation, KeyPackage, workgroup}
 4. Approve (G1)   manager verifies attestation + explicitly admits  ← device-approval gate
 5. Add + re-key   manager MLS-Adds the KeyPackage → group advances to a new epoch
 6. Welcome        client receives the current epoch secret (now shares the group key)
 7. Consent (G2)   first privileged action needs on-device user presence  ← "yes, this can run"
 8. Send/receive   client seals a message to the group; another member opens + attributes it
 9. Revoke         manager MLS-Removes → new epoch; revocation-list entry published
10. Lock-out       removed client cannot decrypt the new epoch and cannot send
```

## Elements needed (and where each lives)

| # | Element | Why | Level-0 file | Level-1 |
|---|---------|-----|--------------|---------|
| 1 | **Identity keypair + KeyPackage** | who the entity is; join credential | `trust/identity.py` | hybrid Ed25519+ML-DSA in Secure Enclave/TPM/StrongBox |
| 2 | **Device attestation + verifier** | basis for approval; proves non-exportable key | `trust/attestation.py` | Secure Enclave / TPM 2.0 quote |
| 3 | **Group session + epoch key** | the workgroup; re-keys on membership change | `trust/group.py` | OpenMLS group (TreeKEM, HPKE, AEAD) |
| 4 | **Member endpoint** | holds current epoch key; opens authorized msgs | `trust/member.py` | MLS client state per device |
| 5 | **Manager / control plane** | admits/removes, two gates, key delivery, revocation list | `trust/control_plane.py` | federated per-workgroup service (§13 D3) |
| 6 | **Revocation list** | total control; lock-out | `Manager.revoked` (set) | signed list + monotonic epoch, propagated |
| 7 | **Transport (mesh)** | reachability | in-process (test) | Tailscale (enterprise) / Headscale (self-host) |
| 8 | **Audit transcript** | tamper-evident Add/Remove history | (future) | MLS hash-chained transcript |

## Security properties the test asserts (`tests/test_trust_join.py`, 4 tests)

- **Zero-trust:** no group key before approval (`bob.has_key` is False pre-approve).
- **Device-approval gate:** invalid attestation ⇒ `approve()` is False, no key.
- **Re-key on membership change:** epoch advances on every Add/Remove.
- **Attribution:** an opened message carries the sender's identity.
- **Post-compromise lock-out:** after Remove, the removed member can neither open
  the new epoch nor seal (NotAuthorized).
- **Revocation is sticky:** a revoked identity can't rejoin even with valid attestation.

## Levels

- **Level 0 (done, 2026-06-08):** stub crypto; validates the *state machine /
  authorization flow*. Runs in <0.05s, no new deps. Clearly NOT a crypto proof.
- **Level 1 (next):** swap `Identity`→hybrid PQ keys (liboqs/ML-DSA), `GroupSession`
  →OpenMLS (MIT, via FFI), `verify_attestation`→real HW quote. Same test file
  passes unchanged. This is the T0/T1 work in `TRUST_MODEL.md` §12.

## Run

```sh
uv run pytest tests/test_trust_join.py -v
```
