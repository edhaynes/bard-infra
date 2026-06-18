# ADR-0016: MVP per-device asymmetric identity + seed-escrow recovery (the client-tier projection of ADR-0009)

Date: 2026-06-18
Status: **Accepted** 2026-06-18 (Eddie blessed the ADR-0009 softening for the MVP tier — see "Reconciliation")
Roadmap tier: v1 — MVP (client tier)
Author: Jason-bard
Subordinate to: ADR-0009 (three-tier identity, the v3 direction), ADR-0008 (tiers)
Relates to: bug #67 (expired baked token — this retires it), the per-device-verifier seams
(`common/device_auth.py:10`, `registry/device_store.py:5`, `contracts/enrollment.schema.json:4`)

## Context

The MVP must: run the **one Flutter client on all three consumer devices** (iPhone, Mac,
Android); let users **create and revoke keys**; **create a box**; and **"ping" each other
over the box**. Today's device identity is **symmetric** — the server mints an HMAC secret at
redeem and keeps a copy (`registry/device_store.py` `admit`/`approve`). Bug #67 showed the
failure mode of treating that secret (or a fleet token) as a baked client credential: it
expires and the client is locked out.

ADR-0009 fixes identity properly but is **explicitly deferred to v3** and is too heavy for the
MVP client tier (three keystores, hybrid-PQ, HW-sealing, MLS). This ADR defines the **MVP
projection** that rides 0009's already-built seams without contradicting its direction.

## Decision

1. **One key, device-generated, software-protected.** Collapse 0009's device·user·application
   triad to a **single per-device Ed25519 identity key**, generated **on the device** at first
   launch. The **private key never leaves the device** (Keychain / Keystore, biometric-gated,
   no iCloud backup). Hybrid-PQ (ML-DSA) and hardware-sealing are deferred to v3 per 0009 — this
   is the "standard assurance / software-protected" tier 0009 already anticipates for no-TPM
   devices (`ADR-0009` §1, device-key TPM-optional note).

2. **Self-signed EdDSA tokens.** The device signs its **own** JWTs (EdDSA / Ed25519); the
   registry and router verify against the **stored public key** through the existing
   `PerDeviceVerifier` seam (the HS256 constant becomes an algorithm parameter). This retires the
   shared HMAC secret on the per-device path (addresses the H-2 single-shared-secret risk for the
   device tier).

3. **Device-generated registration.** enroll/redeem flips: the device sends its **public key**;
   the server stores **only** the public key — no more server-minted `deviceSecret`. Closes #67
   (there is no baked token to expire).

4. **Create / revoke keys.** *Create* = first-launch auto-provision (silent). *Revoke* = the
   existing revoke endpoint, which now removes the stored public key → the device's tokens stop
   verifying at the next request. The box owner can revoke a member.

5. **Two-tier recovery via zero-knowledge seed escrow** (the MVP answer to 0009's open
   "user-key recovery ceremony"). The identity key is derived from a 256-bit **seed**. The seed
   is wrapped **twice** — under an Argon2id key from the user's **app password**, and under a
   one-time **OMG code** (Crockford base32, 3 groups × 5 chars, e.g. `7K3P9-R2M4X-WQ8TB`) — and
   both ciphertexts are escrowed **server-side, keyed by a lightweight account handle**
   (email / username). The server stores **ciphertext only** and can never read the seed.
   Recovery on a new device: handle + password (or OMG code) → fetch ciphertext → decrypt → seed
   → re-derive identity. The OMG code is shown **once**, the on-device copy is then wiped, and it
   is consumed + re-issued after a successful recovery.

6. **Ping over the existing data path, no MLS.** "Ping each other over the box" = a small message
   to box members over Router `/v1/message` (per-device authed; bug #63 fixed). MLS group
   messaging (0009 §3) is v3. Voice / LiveKit is **out of this MVP** — ping is the cross-device
   interaction.

## Reconciliation with ADR-0009 (the conflict, surfaced per process-rules §4)

ADR-0009 mandates *"no plaintext export; recovery must be a social / manager re-enrollment
ceremony, not key export."* The MVP seed-escrow model **does** make the identity recoverable from
a password/OMG-wrapped seed — a **deliberate softening for the cheap, software-key client tier.**
Justification:

- (a) 0009 itself notes a software (no-TPM) device key *"is exportable in principle, so it also
  needs a key-rotation path"* — the MVP tier is exactly that tier.
- (b) The escrow is **zero-knowledge** (the server holds ciphertext it cannot decrypt), so it is
  "hardware-backup-token"-class recovery — one of 0009's own listed alternatives — not server
  custody of keys.
- (c) v3 keeps 0009's HW-sealed / no-export model for the assured tier. **No protocol divergence**
  — only the tier's assurance differs.

This ADR therefore **answers 0009's open "user-key recovery ceremony" item for the MVP tier only.**
It requires Eddie's blessing because it relaxes a recorded invariant.

## Consequences

- Retires the baked fleet token (#67) and the per-device HMAC secret on the device path.
- Introduces a **lightweight account handle** — a departure from the "no-account, one-tap" ethos,
  required so recovery has something to locate.
- Adds a server-side **zero-knowledge escrow store** (ciphertext blobs by handle).
- Adds a Dart Ed25519 path (`dart_jsonwebtoken` ships native EdDSA; + a keygen source) and
  Argon2id + Crockford-base32 on the client.
- Voice / LiveKit is out of this MVP.

## Out of scope (v3, per ADR-0009)

Three-tier device/user/app keys; hybrid-PQ; hardware sealing / attestation; MLS membership and
epochs; social/manager recovery for the assured tier.
