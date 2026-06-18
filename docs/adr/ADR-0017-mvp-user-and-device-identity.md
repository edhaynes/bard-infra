# ADR-0017: MVP user + device identity & user-first onboarding

Date: 2026-06-18
Status: **Accepted** 2026-06-18 (Eddie — on-device testing forced the user layer)
Supersedes: **ADR-0016 §1** (the "single per-device key, no user account" MVP collapse). Restores the user→device key split from ADR-0009 into the MVP — pragmatically (software keys, Ed25519; hybrid-PQ + HW-sealing + MLS stay v3).
Relates to: ADR-0009 (three-tier identity north star), ADR-0016 (device-only MVP identity it amends), bugs #69/#70, features #84/#85, `PLAN_device_identity_mvp.md`.

## Context

ADR-0016 built MVP identity as a **single per-device** Ed25519 key with **no user account**, betting the MVP user owns one box from one device. On-device testing (2026-06-18) broke that bet: a real user has **many devices** (Mac + iPhone + iPad), and the S7 recovery handle is bound to **one** device's key — a second device under the same handle **409s**. The model literally cannot do multi-device-per-user. Eddie's required workflow: **sign in with a username first**, then *this* device gets its own key under that user, and you see the boxes/workgroups **you** (the user) are in.

## Decision

1. **Two key tiers — user + device (ADR-0009, pulled into the MVP).**
   - **User key** — the human's identity, derived from a 256-bit seed; **spans all the user's devices**; identified by a **username** (the account handle). Recovered via the S7 two-tier escrow (password + one-time OMG code), now keyed at the **user** level (escrow handle = username).
   - **Device key** — per-device Ed25519, generated **on-device** (the S3–S5 identity), **enrolled under the user**, with a device name ("Eddie's Mac").

2. **User-first onboarding.**
   ```
   First launch → Sign in (username + password)
     • existing user → sign in → recover the USER key (escrow; OMG on a brand-new device)
     • new user      → create: username, password, one-time OMG recovery code
   → this device generates its DEVICE key, is named, enrolls UNDER the user
       (if device creds already in the Keychain → reuse, skip)
   → land showing the user's BOXES / WORKGROUPS (across all their devices)
   ```

3. **Membership is at the USER level.** Boxes/workgroups have **users** as members; a user participates from **any** enrolled device. (Replaces S5's device-level channel membership — resolves the owner-vs-member and join-vs-own confusion of bugs #69/#70 at the user level.)

4. **Recovery = user-key recovery.** The escrow holds the **user** seed under the username; recovering on a new device restores the user key, then that device mints its own device key under the user.

## Consequences

- **Reworks the identity layer (S3–S7) to add the user dimension:** a **user store** (username → user public key), device records gain a `user`, channel membership becomes **user-level**, escrow keyed by **username**. The device key + the S7 crypto are **reused**, re-homed under the user.
- The device-only model (ADR-0016) is superseded. The two parked branches partly fold in: **#70** (device-level join) → subsumed by user-level membership; **#84** (device naming) → becomes part of user+device onboarding.
- Bigger than ADR-0016, but it's what real multi-device use requires.
- Still pragmatic vs ADR-0009 v3: **software** keys (no HW-seal), **Ed25519** (no hybrid-PQ), **no MLS** — those stay v3, as does the application-key tier.

## Out of scope (v3, per ADR-0009)

Hybrid-PQ keys, hardware sealing/attestation, the per-application key tier, MLS membership/epochs, social/manager recovery.
