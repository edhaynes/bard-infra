# ADR-0009: Three-tier identity keys (device · user · application) and heterogeneous workgroup membership

Date: 2026-06-09
Status: Proposed — **deferred to v3 (Run); direction only, not built, not MVP** (see `ROADMAP.md`)
Roadmap tier: v3 — Run
Author: Jason-bard (PM / acting architect)
Relates to: ADR-0006 (trust front door), ADR-0008 (tiers), ADR-0010 (OO permissions), `TRUST_MODEL.md §3 / §3.1 / §4`, features.md #45 (resolves a/b/g)
Supersedes: the `TRUST_MODEL.md §3.1` working assumption *"the identity key stays device-bound; users and applications are principals expressed on top"* — users and applications now hold their **own** keys.

## Context

`TRUST_MODEL.md §3.1` introduced a device · user · application hierarchy but left the keying open (features.md #45 a/b/g). Eddie 2026-06-09 resolved it:

1. **Key ownership (#45a):** **device + user + application each hold a distinct identity key** — the most granular option. An application can be revoked without revoking its device or user.
2. **Membership edges (#45b/g):** a workgroup admits **devices, users, *or* applications** as distinct member types ("both, by entity type").

## Decision

### 1. Three key types, one certification chain

All three are **hybrid PQ** keypairs (Ed25519 + ML-DSA-65, per §9) and exist **only sealed to hardware** — no plaintext private key ever leaves a device (the §3 ethos is preserved; see §3 reconciliation below).

- **Device key** — HW-backed root on each machine (Secure Enclave / Android StrongBox / **TPM 2.0 — optional**), non-exportable **where hardware exists**. Identity of the physical device.
  - **TPM optional (Eddie 2026-06-09):** with no TPM/enclave the device key is **software-protected** → **standard assurance** (`ROADMAP.md`, `TRUST_MODEL.md §3`). Caveat: "revoking the device is final" holds only for a **non-exportable hardware** key; a **software** device key is exportable in principle, so it also needs a **key-rotation** path, not device-revocation alone.
- **User key** — the human principal, spanning the user's devices. **Not** a free-floating exportable secret: it is **sealed (wrapped) to each enrolled device's HW key**. Enrolling a new device = approval (§7) + re-seal onto that device; it is never copied in the clear. Losing all devices → **recovery via manager/social re-enrollment**, not key export (open sub-decision below).
- **Application key** — per-application, generated on-device, **attested by the device key** ("this app runs here") and bound to the capability grants its user/manager authorizes (#48 / ADR-0010).

**Certification chain (who vouches for whom):** `user key —signs→ device keys` ("these devices are mine") and `device key —signs→ application keys` ("these apps run here, with these caps"). The chain is user → device → application.

### 2. Revocation cascades down the chain

- Revoke an **application** → only that app loses access (device + user unaffected).
- Revoke a **device** → that device and every app on it (the device's whole subtree).
- Revoke a **user** → all of that user's devices and their apps.

Each revocation takes effect at the **next MLS epoch** in every workgroup the revoked entity was a member of (§8 unchanged).

### 3. Heterogeneous workgroup membership

An MLS group (§4, RFC 9420) carries leaves of **three credential types** — device, user, or application — each holding that entity's hybrid PQ key. The credential `type` discriminator lives in `contracts/trust.schema.yaml`. Adding/removing **any** member type rolls the epoch (§1 goal 5). A user-leaf participates in MLS with the **user key directly** (not a stand-in for its devices); a device- or app-leaf likewise uses its own key. Need-to-know (goal 10) is per-leaf: a member decrypts with its own key, nothing more.

## §3 reconciliation (what changes in TRUST_MODEL.md)

- §3.1 working-model line is replaced by this ADR's chain (user → device → app, all keyed).
- Goal 2 ("device-bound keypair; private key never leaves the device") is **refined, not broken**: device keys stay strictly device-bound; **user/application private keys exist only as HW-sealed material on enrolled devices** — "spanning devices" means *re-sealed per device at enrollment*, never plaintext-exported. The "private key never leaves a device in the clear" invariant holds for all three.

## Tier interaction (ADR-0008)

Three keystores + three revocation paths is heavy for the **"ridiculously cheap" client-only tier (< 12, ADR-0008)**. Resolution: the *model* always supports all three, but the **client tier presents a simplified projection** — user + device visible, **applications auto-enrolled under their device** with default-deny caps — while the full per-app granularity and cross-entity revocation UI live in the paid console. No protocol divergence between tiers; only UI surfacing differs.

## Consequences

- **Most key-management surface of the three options** — three enrollment flows, three keystores, three revocation paths. Accepted deliberately for per-app revocation and least-privilege.
- **User-key recovery is the hard new problem** (see open item) — there is no plaintext export, so recovery must be a social/manager re-enrollment ceremony.
- **`trust.schema.yaml` needs a credential `type` discriminator** and the certification-chain fields; the control-plane membership endpoints must accept all three member types.
- **Maps cleanly onto OO permission inheritance (#48 / ADR-0010)** — the user→device→app chain is the natural inheritance spine for capability grants.
- **Effective-identity resolution must be explainable** — given an app leaf, the system must show its device and user ancestors (mirrors the #48 effective-permission resolver requirement).

## Open items (do not block this ADR; flag for a follow-up)

- **User-key recovery ceremony** — manager-assisted vs M-of-N social recovery vs hardware backup token. Needs its own decision before Level-1.
- **Application identity granularity** — one key per app *instance* vs per app *type*; and whether a migrated/updated app rotates its key.
- **Cross-device user-key sealing protocol** — exact wrap/unwrap + new-device attestation handshake (Level-1 crypto detail).

## Alternatives considered

- **Device-bound only.** Simplest, but no per-app/per-user revocation granularity — rejected by Eddie's #45a choice.
- **Device + user (no app key).** Middle ground; apps would inherit the device key and could not be revoked independently — rejected by #45a.
- **Workgroups connect only devices (or only users).** Simpler membership, but Eddie chose heterogeneous "by entity type" (#45b/g) for flexibility (e.g. admit a single application into a workgroup without exposing its whole device).
