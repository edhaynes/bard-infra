# ADR-0006: Zero-trust workgroup identity is the Pro front door (hybrid PQ + MLS), real-crypto-first

Date: 2026-06-08
Status: Proposed — **deferred to v3 (Run); direction only, not built, not MVP** (see `ROADMAP.md`)
Roadmap tier: v3 — Run
Author: Jason-bard (PM / acting architect)
Supersedes: the MVP JWT auth posture in `contracts/` + `DESIGN.md §3` (kept behind a verifier interface until this lands)
Depends on: `TRUST_MODEL.md` (design), `TRUST_TEST_PLAN.md` (Level-0 join harness)

> Note: the MVP ADRs **0001–0005 are not yet written** (tracked as owed in project
> memory + features backlog). This ADR is numbered 0006 to reserve its slot per
> `TRUST_MODEL.md §14`; it does not depend on 0001–0005 existing, but they remain owed.

## Context

`TRUST_MODEL.md` designed a zero-trust workgroup identity fabric (per-entity
hybrid-PQ identity keys, per-workgroup MLS group key re-keyed on every membership
change, two-gate device approval, total revocation, trust-translation bridging).
Decisions **D1–D5 were accepted 2026-06-07** and the deps confirmed (OpenMLS MIT
v0.8.1; Headscale BSD-3 v0.28.0). It was scoped as **post-MVP**.

On **2026-06-08**, reviewing the Flutter client tab-by-tab, Eddie reframed the
product: *registering the local device and creating/joining workgroups is "one of
the first things a user does … it's the whole point."* The trust fabric is not a
feature on Pro — it **is** Pro; LLM serving (router/agents/models) is what
workgroup membership unlocks and rides on top of. That reframing forces several
decisions this ADR records.

## Decision

1. **The trust layer is promoted from post-MVP to the MVP front door.** Device
   registration + workgroup create/join is onboarding / critical path, not a
   secondary panel. (features.md #44.)
2. **The client's Dashboard becomes "Home"** — identity + workgroups are the
   primary content; backend health/metrics are secondary. A **first-run gate**
   routes a user with no identity / no workgroup straight into register → create/
   join before the other tabs (Terminal/Chat/Models) are usable.
3. **Tab 1 "Connections" becomes "Workgroups."** Backend endpoints come *from*
   workgroup membership — the control plane returns the workgroup's reachable
   router/agents (`GET /workgroups/{id}/endpoints`). Hand-entered router/registry
   URLs survive **only as a dev/local fallback**. This **reverses the earlier
   Tab-1 "Option A: single hand-entered front door" decision** for production:
   membership is the front door; manual entry is the escape hatch.
4. **Real-crypto-first.** Onboarding does **not** ship on the Level-0 stub crypto.
   Level-1 (real hybrid-PQ identity keys in hardware + OpenMLS group engine + real
   attestation) lands before the onboarding UI goes live. The Level-0 state
   machine (`trust/`, `tests/test_trust_join.py`) stays as the behavioural spec the
   real implementation must satisfy unchanged.
5. **macOS / Secure Enclave first, then fan out.** To keep "real-crypto-first"
   honest without blocking the first demo on five simultaneous native keystore
   integrations: land real OpenMLS + hybrid-PQ on **macOS (Secure Enclave)** end to
   end, prove the full join (bootstrap → attest → approve → re-key → send → revoke
   → lock-out) with real crypto, **then** port the keystore to TPM 2.0 (Win/Linux)
   and StrongBox (Android), iOS Secure Enclave.
6. **Crypto suite is frozen per `TRUST_MODEL.md §9`** (no re-litigation): identity =
   Ed25519 + ML-DSA-65 (FIPS 204); group KEM = X25519 + ML-KEM-768 (FIPS 203, HPKE
   RFC 9180); group lifecycle = MLS / TreeKEM (RFC 9420) via **OpenMLS**; content
   AEAD = AES-256-GCM / ChaCha20-Poly1305. Hybrid everywhere.
7. **Federated control plane (D3).** Each workgroup is its own trust domain with
   its own manager(s); no global coordinator. The control plane is a **distinct
   service contract** (`contracts/control-plane.openapi.yaml`), reachable under the
   Router origin (the Tab-1 Option-A "single front door" still holds at the
   *transport* level: one base URL proxies router + control plane).

## Sequencing (what this commits us to building, in order)

1. **T0 contract freeze** — `contracts/control-plane.openapi.yaml` +
   `contracts/trust.schema.yaml` (identity key format, KeyPackage, attestation,
   capability claim, workgroup/member records, revocation entry). *This ADR ships
   with the first draft of those.*
2. **T1 (macOS-first):** hardware keystore (Secure Enclave) · OpenMLS engine via
   FFI · liboqs/ML-DSA + ML-KEM via FFI · live control-plane endpoints replacing
   the Level-0 stubs · real attestation + verifier.
3. **Home + Workgroups UI** (Flutter) bound to the real endpoints.
4. **Fan-out:** TPM 2.0, StrongBox, iOS keystores behind the same interface.

## Consequences

- **New dependencies (flagged per CLAUDE.md hard rule #5 — require sign-off):**
  - **OpenMLS** — Rust, MIT v0.8.1; consumed via FFI. (Vetted, `TRUST_MODEL §13.1`.)
  - **liboqs / `oqs`** — C, Apache-2.0; ML-DSA-65 + ML-KEM-768. **ARM build must be
    confirmed** before adoption.
  - **Dart↔Rust/C FFI bridge** — `flutter_rust_bridge` (MIT/Apache) or hand-rolled
    `dart:ffi`. New dep + build toolchain.
  - **Per-platform keystore** — Secure Enclave / TPM 2.0 / StrongBox: native
    platform-channel code on each target (not a single pub package).
- The MVP demo is now gated on real crypto on macOS, not on stubs — slower first
  light, but no throwaway and no false sense of security.
- `metadata.authToken` (MVP JWT) stays behind the verifier interface until the
  PQ-identity verifier replaces it; the wire envelope (`protocol.schema.json`) is
  unchanged — only the verifier swaps.
- Hand-entered connections become a dev affordance; production UX assumes
  membership-derived endpoints.

## Alternatives considered

- **Stub-now, real-later** (build onboarding UI on the Level-0 state machine, swap
  real crypto in behind seams). Rejected by Eddie 2026-06-08: shipping a security
  front door on placeholder crypto risks a false sense of security and a
  throwaway UI contract.
- **Keep trust post-MVP; ship hand-entered Connections as the MVP front door.**
  Rejected: contradicts the product thesis ("it's the whole point").
- **All-platform keystore in parallel.** Rejected for first light: five native
  integrations blocking one demo. macOS-first de-risks (decision 5).
- **Dedicated Identity tab / six tabs.** Rejected: Home already is the identity
  surface; Workgroups carries membership. Five tabs hold.
