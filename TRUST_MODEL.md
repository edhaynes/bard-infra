Status: Not Implemented — **deferred to v3 (Run); direction only, not an MVP commitment** (see `ROADMAP.md`). Drafted 2026-06-07; "D1–D5 accepted" = accepted *direction for v3*, not built. TPM-optional tiering folded in 2026-06-09.

# Bard — Zero-Trust Identity & Workgroup Trust Model

> Companion to `DESIGN.md`. Defines how entities prove who they are, how
> workgroups are formed and re-keyed, how messages cross workgroup boundaries,
> and how anything can be revoked. Built on **known-good templates** (CLAUDE.md
> "rock-solid, template-first"): Tailscale/WireGuard for the zero-trust control
> plane, **MLS (RFC 9420)** for group keying, **HPKE (RFC 9180)** for envelope
> encryption, and the **NIST PQ standards** (FIPS 203/204/205) for the crypto.
> We do not invent primitives.

---

## 1. Goals

1. **Zero trust.** No entity is trusted by network location. Every message is
   authenticated and authorized on its own merits — exactly the Tailscale model
   (a packet from "inside the LAN" earns nothing).
2. **Per-entity identity.** Every entity (agent / router / client) owns a
   device-bound keypair. The private key never leaves the device.
3. **Mandatory device approval — "yes, this can run."** A new entity joins only
   after an explicit human/device approval, and privileged actions require
   user-presence on the physical device. Network reachability alone never
   authorizes anything.
4. **Workgroups with managed membership.** A workgroup has a **manager** who
   admits/removes members. Roles are **per-workgroup** — a plain member of WG-A
   can be the manager of WG-B.
5. **Shared workgroup key, re-keyed on every membership change.** Each workgroup
   has a current shared group secret; adding or removing a member rolls it to a
   new epoch so departed members can't read future traffic and new members
   can't read past traffic. (This is your "shared private key, revoked as
   members change" — formalized by MLS.)
6. **Multi-membership + bridging.** An entity in several workgroups can relay
   messages between them under explicit, auditable rules.
7. **Total control + instant revocation.** A manager can revoke a key or a
   device and have it take effect at the next epoch, everywhere.
8. **Post-quantum.** Resistant to "harvest-now-decrypt-later" and to a future
   quantum adversary forging identities. **Quantum-resistant cryptography is used
   throughout** (Eddie 2026-06-09) — identity, key agreement, transport, *and* the
   keys that protect data at rest (goal 9) are PQ/hybrid, never classical-only.
9. **Encryption at rest — everywhere** (Eddie 2026-06-09). *All* persisted data is
   encrypted on disk: the Valkey source of truth (AOF/RDB + backups, ADR-0010),
   agent volumes, model stores, logs, and caches. Data-encryption keys are wrapped
   by PQ/hybrid key-encryption keys (goal 8) and are **never co-located** with the
   ciphertext they protect. A stolen disk or backup reveals nothing.
10. **Need-to-know at intermediate nodes** (Eddie 2026-06-09). Payloads stay
    **end-to-end encrypted** (MLS group + HPKE, §4/§9); an intermediate node — mesh
    relay, router, bridge (§6) — is revealed **only** the routing/authorization
    metadata it strictly needs to forward, **never** the cleartext content. A relay
    that is itself a workgroup member sees content for *that* workgroup only;
    bridging (§6) re-encrypts per destination epoch rather than passing plaintext
    through. Least-disclosure is the default at every hop.

### Non-goals (for the first cut)
- Anonymous membership (we want attribution).
- A global naming authority — identity is federated per workgroup.

> **Revised 2026-06-08 (features.md #45):** *hiding* objects is now **in scope** —
> within an organization, workgroups (and devices) may be **hidden** (not
> discoverable) vs **visible** (browsable). The earlier "hiding workgroup
> existence" non-goal is withdrawn. See §3.3.

---

## 2. Mental model — "a Tailscale tailnet per workgroup"

| Tailscale concept | Bard equivalent |
|-------------------|--------------------------|
| Tailnet | Workgroup |
| Node (device with a WireGuard key) | Entity (device with a PQ identity key) |
| Admin console / coordination server | Workgroup **manager** (federated, per workgroup) |
| **Device approval** before a node joins | Manager **admits** an entity (signed MLS Add) |
| Key expiry | Identity-key + epoch expiry (defense in depth) |
| ACLs / tags | Per-workgroup roles + capabilities |
| Revoke a node | Manager **removes** member → group re-key |
| WireGuard data plane (encrypted P2P) | MLS group + HPKE messages over the mesh |

Difference from Tailscale: there is no single global coordinator. Each workgroup
is its **own** trust domain with its **own** manager(s); an entity is a member of
many, and is the only thing that links them (see §6 bridging).

---

## 3. Identities

- Each entity generates an **identity keypair**, in **hardware-backed,
  non-exportable** storage **where available** — Secure Enclave (iOS/macOS),
  Android StrongBox/Keystore, or **TPM 2.0 (Windows/Linux — optional, not required)**.
  **TPM is optional (Eddie 2026-06-09):** on a device without a TPM/enclave the key lives
  in a **software-protected keystore** (OS keystore / encrypted-at-rest software key).
- This yields **two-tier device assurance**, not a hardware binary:
  - **High assurance** — hardware-backed, non-exportable key (± attestation). For a
    hardware key, "revoke the device" is sufficient and complete. Eligible for privileged
    roles / sensitive workgroups.
  - **Standard assurance** — software-protected key when no TPM/enclave. The device still
    joins; the manager sees the lower assurance level and policy-gates what it may do.
    A software key is exportable in principle, so it also needs a **key-rotation** path
    (device-revocation alone is not final for software keys).
- **Algorithm (hybrid PQ — recommended):** the identity key is a **hybrid
  signature**: classical **Ed25519** + PQ **ML-DSA-65 (FIPS 204)**. A signature
  is valid only if *both* verify. This is the IETF/NIST migration posture: we
  get PQ security now without betting everything on a young primitive.
  - This answers feature #42's open (i)-vs-(ii): **PQ identity from day one, but
    hybrid** — not a literal `ssh-keygen` key (stock OpenSSH has no PQ identity
    key), and not classical-only.
- Identity public keys are published into the workgroups the entity belongs to
  (§4). An identity is just "this hybrid public key"; human-readable names are
  per-workgroup labels, not a global registry.

---

## 3.1 Entity hierarchy — devices, users, applications

The flat "entity" above resolves into **three kinds**, because the fabric is
fundamentally **a connection of devices** (Eddie 2026-06-08):

- **Device** — the physical machine. **Holds the hardware-backed, non-exportable
  hybrid-PQ identity key** (§3); revoking the device is therefore final. A device
  advertises a **capability profile — CPU, GPU, memory, networking, storage** —
  which structures the registry's flat `capabilities[]` and
  `power-profile.schema.yaml` and drives capability-based routing / remote compute
  (feature #41). The mesh links devices.
- **User** — the human principal. **Owns** one or more devices (the "independent"
  personal network in §3.2 is one user + their devices). A logical identity
  layered over their devices' keys.
- **Application** — a software entity that **runs on** a device (the Bard agent,
  the router, the registry, the client). Acts under the device's identity within
  the capabilities its user/manager grants.

**Resolved 2026-06-09 (ADR-0009, features.md #45 a/b/g):** *user owns devices;
applications run on devices; **workgroups admit devices, users, or applications as
distinct member types**.* **All three hold their own hybrid-PQ key** — device
(HW-root), user (sealed per-device, spans a user's devices), application (on-device,
attested by the device key). Certification chain **user → device → application**;
revocation cascades down it. No plaintext private key ever leaves a device. This
**supersedes** the earlier "identity key stays device-bound; users/apps are
principals on top" assumption. See ADR-0009 for the keystore, recovery, and tier
(client-only <12) interactions.

## 3.2 Identity scope — independent vs organization (enroll mode)

At **enroll** (§7 gate 1) an identity picks a scope:

- **Independent** — the user sets up their **own personal network of devices**.
  No organization (an implicit personal scope); they create/join workgroups among
  their own and invited devices.
- **Organization** — the user enrolls into a **managed multi-user org**. The org
  is a first-class scope **above** workgroups; within it the user can **browse
  visible workgroups** (§3.3) and request to join.

An independent user can later **join an organization** (resolved, features.md #45 d),
bringing their devices under the org scope. **Their pre-existing personal workgroups
stay personal** — org membership is **additive**, not a takeover; the org admin gains
no visibility or governance over workgroups the user created in their independent scope.
The org *is* a first-class scope above workgroups (#45 c); independent = an implicit
personal scope with no org.

> **Client-sufficiency (Eddie 2026-06-09).** Independent users and **small
> businesses (< 12 devices/users)** must operate with **the Flutter client alone**
> — device registration, workgroup create/join, member admit/approve, and basic
> permission grants are all available in-client at this scale. The React
> **management console is an enterprise/org-scale add-on**, not a dependency for
> small scale. See ADR-0008 "Scale & commercial tiers" and features.md #49.

## 3.3 Visibility — visible vs hidden

Within an organization, objects carry a **visibility**:

- **Visible** — listed in org discovery; any org member sees it exists and may
  request to join (subject to the two-gate approval, §7).
- **Hidden** — **not** listed; reachable only by direct invite / id. Applies to
  **workgroups and devices**. (The §1 non-goal deliberately reversed 2026-06-08.)

**Resolved 2026-06-09 (features.md #45 e/f):**
- **(e) Hidden = existence concealed even from the control plane.** A hidden object's
  existence is *not* enumerable by the control plane — it stores only **blinded
  handles**, never a cleartext listing, so a compromised or curious operator cannot
  discover hidden workgroups/devices. This is the strong, zero-trust-consistent option
  (not merely "unlisted"). ⚠️ **Architectural implication (carve-out from ADR-0010's
  "control plane sees all authoritative state"):** hidden-object discovery/membership
  uses a **blinded-handle / private-lookup** mechanism (only an invitee who can compute
  the handle can resolve it); hidden-object state the control plane holds must be
  opaque ciphertext keyed by handles members derive. The concrete protocol (PSI /
  oblivious lookup / capability-URL) is a **follow-up design item** — see §14 / a future
  ADR. The decision (conceal from control plane) is fixed; the mechanism is TBD.
- **(f) Visibility is set layered, by both.** The **org admin** sets org-wide
  visibility *policy, defaults, and caps*; the **workgroup manager** sets per-workgroup
  visibility **within** those bounds.

**Visibility applies inside an org.** Independent/personal scope has no org discovery to
hide from; personal workgroups are private to the user's mesh by construction.

---

## 4. Workgroups & the shared group key (MLS)

A workgroup is an **MLS group** (RFC 9420). MLS gives us, off the shelf,
precisely the lifecycle in goal #5:

- **Add member** → manager issues an MLS *Add* + *Commit*; the group advances to
  a new **epoch** with a fresh shared secret. The new member can decrypt from
  this epoch forward only (no history).
- **Remove member** → manager issues *Remove* + *Commit*; new epoch, new secret.
  The removed member is cryptographically locked out of all future traffic
  (**post-compromise security**), without re-keying being a manual chore.
- **Forward secrecy:** compromising today's epoch secret does not expose past
  epochs.
- The "shared workgroup private key" you described is the MLS **epoch secret**,
  from which per-message keys are derived. MLS's TreeKEM makes re-keying
  O(log n) instead of "re-encrypt for everyone," so rotation-on-every-change is
  cheap even for large workgroups.

**Confidentiality vs attribution (important design note).** A *single shared
private key used for signing* would mean any member could impersonate the group
and you couldn't tell who sent what. So we split it the standard MLS way:
- **Group key (shared, per-epoch)** → message **confidentiality** + membership
  gating. This is the shared secret you want.
- **Per-entity identity key (§3)** → message **authenticity/attribution**: every
  message is also signed by its sender's hybrid identity key.

So "shared key, rotated on membership change" = confidentiality, and we keep
per-sender signatures so revocation and audit remain meaningful.

**PQ for the group:** MLS encrypts key material with **HPKE (RFC 9180)**; we use
a **hybrid HPKE ciphersuite** (X25519 + **ML-KEM-768 / FIPS 203**) so the group
key agreement is PQ too. Content is sealed with **AES-256-GCM** (or
ChaCha20-Poly1305 on platforms without AES-NI).

---

## 5. Roles, delegation, and the manager

- Roles are **scoped to a workgroup**, encoded as signed capability claims in the
  member's leaf in the MLS tree. Minimum roles: `manager`, `member`. (Future:
  `auditor` read-only, `bridge` allowed-to-relay.)
- A `manager` capability authorizes: admit member, remove member, assign/revoke
  roles, force re-key, set expiry/ACLs.
- **Delegation across workgroups is automatic from scoping:** being a `member`
  of WG-A carries no authority in WG-B; WG-B's manager grants WG-B's
  `manager` capability independently. Hence "a member of one workgroup can manage
  a different workgroup" falls straight out — there is no global role.
- Multiple managers per workgroup allowed (avoids single-point-of-failure);
  manager actions are signed and logged to the group transcript (MLS keeps a
  hash-chained transcript, giving tamper-evident audit for free).

---

## 6. Cross-workgroup messaging (bridging)

An entity in WG-A and WG-B can pass a message between them. Two models — we
**recommend (a)** for the first cut:

- **(a) Trust-translation relay (recommended).** The bridge entity decrypts in
  WG-A (it's a legitimate member), then **re-encrypts and re-signs** into WG-B
  under its own WG-B identity. WG-B sees the message as *from the bridge*, not
  from the WG-A sender. Pros: clean trust boundary — WG-B never sees WG-A
  identities or keys; revoking the bridge cleanly severs the link. Cons: the
  bridge is trusted to relay faithfully (mitigated by audit transcript).
- **(b) End-to-end across groups.** Requires the WG-A sender and WG-B recipients
  to share identity-level keys directly — leaks identities across the boundary
  and complicates revocation. Deferred.

**Safety rails (mandatory for either):**
- **Loop prevention:** each message carries a path vector of workgroup IDs it has
  traversed; a bridge drops a message whose next hop is already in the path.
- **TTL / hop limit:** monotonically decremented; 0 ⇒ drop.
- **Explicit bridge capability:** relaying requires the `bridge` role in *both*
  workgroups, set by each workgroup's manager — so cross-pollination is opt-in,
  not a side effect of multi-membership.

---

## 7. Device approval — "yes, this can run"

Two gates, both mandatory (zero-trust = authorize every time, not once):

1. **Control-plane admission (manager).** A new entity presents its identity
   public key and, **where the hardware supports it, an attestation** (Secure Enclave /
   TPM quote proving the key is non-exportable and the device is genuine). **Attestation is
   optional (TPM optional, Eddie 2026-06-09):** when absent, the entity joins at **standard
   assurance** and the assurance level is recorded on its MLS leaf so the manager can
   policy-gate it. The manager explicitly approves — an MLS *Add*. Equivalent to Tailscale
   device approval. No auto-join.
2. **Device-local consent (physical presence).** The identity private key is
   gated by **user presence** (biometric / passcode) on the device. Privileged
   or first-run actions ("this agent may start", "this container may run",
   "relay between WG-A and WG-B") require a fresh on-device approval, so a remote
   attacker with full network access still cannot make the device act. This is
   the literal "yes, this can run on the physical device."

Defense in depth: **key expiry** (Tailscale-style) forces periodic re-approval;
expired keys are treated as revoked until re-approved.

---

## 8. Revocation — total control

- **Revoke a member:** manager issues MLS *Remove* → next epoch excludes them →
  they cannot decrypt any future message in that workgroup. Because identity keys
  are non-exportable, removing the device is final.
- **Revoke an identity globally:** publish a signed entry to a **revocation list**
  keyed by identity-key hash, with a **monotonic epoch counter**; every workgroup
  the entity belongs to processes a *Remove*. Entities reject signatures from
  revoked keys even if cached.
- **Propagation:** revocations ride the control plane (the manager(s)); offline
  entities reconcile the revocation epoch on reconnect before trusting anyone.
- **Compromise response:** rotate the affected workgroup epoch immediately (PCS),
  expire the device key, require re-attestation to rejoin.

---

## 9. Crypto suite (summary)

| Purpose | Primitive (hybrid) | Standard |
|---------|--------------------|----------|
| Identity signature | Ed25519 **+** ML-DSA-65 | FIPS 204 |
| Group key agreement (HPKE KEM) | X25519 **+** ML-KEM-768 | FIPS 203, RFC 9180 |
| Group lifecycle / re-key | MLS / TreeKEM | RFC 9420 |
| Content AEAD | AES-256-GCM / ChaCha20-Poly1305 | — |
| Data at rest (goal 9) | AES-256-GCM DEK, wrapped by hybrid X25519 **+** ML-KEM-768 KEK | FIPS 203 |
| Transport (mesh) | WireGuard-style Noise + PQ KEX; or TLS 1.3 + PQ KEX | — |
| SSH CLI tab transport (#38) | OpenSSH PQ KEX `mlkem768x25519-sha256` | — |
| Key store | Secure Enclave / Android StrongBox / **TPM 2.0 (optional)**; **software keystore fallback = standard assurance** | — |

Hybrid everywhere: a break of *either* the classical or the PQ half must not
break the whole. (SLH-DSA / FIPS 205 is held as a conservative backup signature
if ML-DSA needs replacing.)

---

## 10. Relationship to the MVP contracts

- This **supersedes the MVP's JWT auth** (DESIGN.md §3 / `contracts/`). Until it
  lands, lanes keep `metadata.authToken` validation **behind an interface** so a
  PQ-identity verifier can replace the JWT verifier without touching call sites
  (DESIGN.md §8h). The wire envelope is unchanged; only the verifier swaps.
- It also **subsumes the deferred mesh** (DESIGN.md §2): the zero-trust transport
  here *is* the mesh, so a separate Tailscale dependency may become unnecessary —
  or Tailscale becomes one pluggable transport among others.

---

### 10.1 Self-hosted mesh: Tailscale clients + Headscale headend

If we want the *real* mesh (not just the analogy), it can be **fully open source
and self-hosted** — no dependency on Tailscale the company:

- **Tailscale client** (`tailscale/tailscale`) — **BSD-3-Clause**, open source.
  The data plane (WireGuard/Noise) and the CLI/daemon are OSS.
- **Tailscale coordination server is proprietary.** The OSS replacement is
  **Headscale** (`juanfont/headscale`, **BSD-3-Clause**) — a self-hostable
  reimplementation of the control "headend": node registration, key distribution,
  ACLs, MagicDNS, subnet routers, exit nodes. This maps cleanly onto our
  **manager / control-plane** role (§5, §7).

**Maturity (verify before committing — knowledge cutoff Jan 2026; confirm current
state):**
- Headscale is **pre-1.0 (0.x)** but widely deployed in the self-hosting
  community; single binary, SQLite or Postgres backing.
- It **tracks a moving target**: it implements the control protocol the Tailscale
  client expects, and each client release advertises a *supported version range*.
  A client update can outrun Headscale → **compatibility breakage** is the main
  operational risk, and exactly why an update pipeline (below) is needed.
- HA / horizontal scaling is limited (built for personal/small-team scale);
  Postgres helps but it is not a clustered control plane out of the box. For our
  **federated per-workgroup** model that may be fine — many small headends rather
  than one big one.
- Feature lag vs the official control plane is expected; check each release's
  support matrix.

**Upstream-tracking pipeline (feature #43).** Because both halves move:
1. **Watch** `tailscale/tailscale` and `juanfont/headscale` release tags
   (Renovate/Dependabot or a scheduled GitHub Action).
2. **Pin** both versions; maintain a tested **compatibility matrix**
   (Headscale × Tailscale-client) — never auto-bump into prod.
3. **CI gate:** rebuild the UBI-9 image with pinned versions and run a smoke
   suite (node join → ACL enforced → key expiry → manager revoke → re-key) before
   promotion.
4. **Staged rollout:** dev → canary workgroup → prod; auto-rollback on smoke
   failure.
5. **Track Headscale's documented supported-client range** and refuse client
   versions outside it.

**The headend is the pluggable part — and we do NOT try to compete with
Tailscale.** Building and supporting a NAT-traversing zero-trust mesh at
Tailscale's level is not our business; we integrate with theirs and put our value
(identity + MLS workgroups, §3–§9) on top. Same OSS Tailscale client either way;
the control plane is the client's choice:
- **Official Tailscale supported control plane — RECOMMENDED for enterprise.**
  Vendor-supported, SLA-backed, maintained by the people who build the protocol.
  Enterprises pay Tailscale and point the client at `controlplane.tailscale.com`.
  This is the default recommendation for any serious/production deployment.
- **Self-hosted Headscale (OSS) — for self-host / air-gapped / no-vendor.** Full
  control, no vendor dependency, fits the federated per-workgroup model — but the
  client carries the ops + the #43 compatibility pipeline. Choose it when policy
  forbids a SaaS control plane, not to save money on support we'd then have to
  provide ourselves.

We ship one transport adapter with a configurable login-server / control URL
(CLAUDE.md §1 — config, not hardcoded); clients pick supported Tailscale **or**
Headscale. The mesh is a **pluggable transport**; our MLS/identity layer rides on
top and does not depend on it for security (defense in depth — the mesh encrypts
transport, MLS secures the group regardless of headend).

---

## 11. Threat model (abbreviated)

| Threat | Mitigation |
|--------|------------|
| Harvest-now-decrypt-later | PQ KEM in HPKE + PQ transport KEX |
| Quantum forgery of identity | PQ ML-DSA half of the hybrid signature |
| Stolen device | Non-exportable key + user-presence gate + remote revoke |
| Malicious/compromised member | Per-epoch FS+PCS; remove → instant lockout |
| Rogue bridge | Audit transcript; `bridge` role revocable; path/TTL limits |
| Network attacker (zero-trust) | Every message authn+authz; location grants nothing |
| Replay / loops across workgroups | Path vector + TTL + per-message nonce |

---

## 12. Phasing

This is **post-MVP** and large; it gets its own phase, decomposed for parallel
lanes like DESIGN.md:
- **T0 (serial, contract freeze):** identity key format, MLS ciphersuite choice,
  revocation-list schema, capability-claim schema, attestation format. Frozen in
  `contracts/` like Phase 0.
- **T1 (parallel):** identity/keystore lib (per-platform HW backing) · MLS group
  engine (wrap a vetted MLS impl — do **not** hand-roll) · manager/control-plane
  service · bridge/relay logic · revocation service · device-approval UX (Flutter).
- **T2 (integration):** end-to-end across two workgroups with a bridge, revoke,
  re-key, audit.

**Use a vetted MLS implementation** (e.g. OpenMLS in Rust via FFI, or a
maintained binding) — hand-rolling MLS/TreeKEM is exactly the kind of thing the
"known-good templates" rule forbids.

---

## 13. Decisions (D1–D5 accepted 2026-06-07)

**These are accepted *direction for v3 (Run)*, not MVP commitments** (see `ROADMAP.md`) — they
guide the deferred trust layer, and earn an "Accepted/built" stamp only when v3 code lands.
Two carry a dependency-review prerequisite (§13 of CLAUDE.md) closed by the research spike in
§13.1.

- **(D1) Hybrid PQ — ACCEPTED.** Identity = Ed25519+ML-DSA-65; group KEM =
  X25519+ML-KEM-768. Not pure-PQ.
- **(D2) MLS implementation = OpenMLS — ACCEPTED & CONFIRMED (§13.1).** MIT,
  v0.8.1, RFC 9420; client-side engine is the ready part we use. Rust core via
  FFI; never hand-roll MLS/TreeKEM.
- **(D3) Federated per-workgroup control plane — ACCEPTED.** Each workgroup is its
  own trust domain with its own manager(s); no global coordinator.
- **(D4) Cross-workgroup bridging = trust-translation relay (§6a) — ACCEPTED** for
  v1, with path-vector + TTL + explicit `bridge` role.
- **(D5) Mesh = pluggable transport; we do NOT compete with Tailscale —
  ACCEPTED & CONFIRMED (§13.1, §10.1).** Recommended for **enterprise: official
  supported Tailscale** (vendor SLA). **Self-host/air-gapped: Headscale** (BSD-3,
  v0.28.0, pre-1.0 → the #43 compatibility pipeline applies). Same OSS client,
  configurable login server. Our value sits *on top* (identity + MLS), not in the
  mesh.

### 13.1 Research spike — dependency confirmation (§13, done 2026-06-07)

**OpenMLS (D2) — CONFIRMED, adopt.**
- **License: MIT** (permissive — earlier AGPL worry was wrong). ARM-clean (Rust).
- **Latest: v0.8.1 (Feb 2026)**, actively maintained by Phoenix R&D + Cryspen;
  RFC 9420.
- **Maturity:** still **pre-1.0**. The **client-side group engine** (group state,
  message in/out, key schedule, TreeKEM) is the ready, usable part — which is
  exactly what we consume. Its **server/delivery-service** stubs are *not*
  production-ready — fine, because we build our own federated control plane (D3)
  and don't use those stubs.
- **Action:** pin a version; wrap behind our own interface; FFI from the control
  plane / agents. Track releases (still 0.x → expect breaking changes).

**Headscale (D5/#43) — CONFIRMED, adopt as the self-hosted option.**
- **License: BSD-3-Clause.** Self-hosted Tailscale-compatible control server.
- **Latest: v0.28.0 (mid-2025).** Still **pre-1.0** but actively maintained;
  notably **HA has improved** — it now probes HA subnet routers over the Noise
  channel and fails over to a healthy standby (default 10s probe / 5s timeout)
  when 2+ nodes advertise the same prefix. Good signal for our needs, though it
  is still not a clustered control plane.
- **Maturity caveat stands:** 0.x + it tracks the Tailscale client protocol →
  the **compatibility-gate pipeline (#43) is required**, not optional.
- **Action:** pin Headscale + client versions; treat as pluggable transport; our
  MLS/identity security does not depend on it.

Both deps are permissive-licensed (MIT + BSD-3) and ARM-clean. Both are pre-1.0,
so: pin versions, wrap behind interfaces, and gate upgrades through CI (#43).

---

## 14. Next steps

0. **Join workflow test — Level 0 done 2026-06-08.** See `TRUST_TEST_PLAN.md` +
   `trust/` + `tests/test_trust_join.py`: the client-join state machine
   (bootstrap → attest → approve → re-key → send → revoke → lock-out) runs with
   stub crypto. Level 1 swaps in OpenMLS + hybrid PQ keys behind the same
   interfaces (the test passes unchanged).
1. ~~Sign off D1–D5.~~ **Done 2026-06-07** (accepted + deps confirmed, §13.1).
2. Write **ADR-0006: Zero-trust workgroup identity (hybrid PQ + MLS)** referencing
   this doc (after the MVP ADRs 0001–0005).
3. Freeze the T0 contracts (identity key format, MLS ciphersuite, revocation-list
   schema, capability-claim schema, attestation format).
4. Decompose T1 into lanes and build.
5. **Design the blinded-handle / private-lookup protocol for hidden objects (§3.3 e).**
   Concealing existence from the control plane needs an oblivious-discovery mechanism
   (PSI / capability-handle / oblivious lookup) so an invitee can resolve a hidden
   workgroup/device without the control plane being able to enumerate it. Decision is
   fixed (conceal from control plane); the *mechanism* is open → its own ADR.
6. **User-key recovery ceremony (ADR-0009 open item).** Recover a user identity with no
   plaintext key export, working for both org (manager-assisted) and independent
   (no-manager) users. Research spike in flight → own ADR.
