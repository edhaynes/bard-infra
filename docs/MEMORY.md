# Project Memory — Bard

Running log of standing preferences and gotchas (CLAUDE.md §12). Not ADR-worthy on
their own, but must not be forgotten. Newest decisions on top.

## Standing decisions (Eddie 2026-06-27 session)

- **`JOURNAL.md` is this repo's living status/history — READ IT AT SESSION START**
  (before PLANS.md/bugs.md/features.md). Canon: `shared-rules/process-rules.md §5`.
  Entries are **timestamped, newest-on-top, "latest is greatest"** — a newer
  entry supersedes older ones on conflict (retire a decision by adding a newer
  entry, not by editing history). Per-repo `JOURNAL.md` = this repo;
  `~/projects/JOURNAL.md` = cross-project (Jason-meta, from the projects root).
  Anti-stale enforcement lives in `shared-rules/hooks/check_plan_tracker_status.py`
  (fails commits when a plan isn't tracked in PLANS.md or JOURNAL.md is missing).

- **Thread discipline (Eddie 2026-06-27):** keep **≤2, max 3** threads/windows
  open at once; Jason MUST push back and corral when it sprawls (parks extras to
  trackers/journal). Reinforces coding-rules §15 "contain tangents; hold the
  through-line."

## Standing decisions (Eddie 2026-06-09 session)

- **Roadmap = crawl/walk/run; MVP scope locked (`ROADMAP.md`, authoritative over DESIGN.md).**
  v1 Crawl = one LAN, real model, JWT. v2 Walk = ssh tab, remote spawn, Valkey + control
  plane, React console, OO domain model w/ software-key trust, opt-in mesh. v3 Run = full
  zero-trust PQ + MLS fabric. **MVP forks (locked):** inference = **llama.cpp in the agent**
  (LiteLLM routes to it; vLLM/"Athena" is a backend, not a router); **ssh CLI tab → v2**;
  **remote agent spawn/lifecycle → v2**; registry persistence = **JSON-file** behind
  `store.py` (Valkey lands with the control plane in v2). MVP ADRs **0001–0005 written**;
  trust-layer ADRs **0006–0010 + TRUST_MODEL = Proposed, deferred to v2/v3 (direction only,
  not built)**.

- **Sprints to MVP = 0–4** (`ROADMAP.md`): 0 reconcile/freeze (done) · 1 llama.cpp inference ·
  2 Flutter client wired to router · 3 end-to-end on one LAN · 4 package/CI/docs/release.
  ssh tab = Sprint 5, remote compute = Sprint 6 (both v2).

- **Client platform priority = macOS + iOS first, designed to run on Windows + Linux**
  (Eddie 2026-06-09; ADR-0005). One Flutter codebase, no platform-specific UI forks, no
  mac/iOS-only API without a documented Windows/Linux fallback; Windows/Linux/Android keep
  building (CI macOS + Linux) but are polished after mac/iOS.

- **TPM is optional → two-tier device assurance** (Eddie 2026-06-09; TRUST_MODEL §3/§7,
  ADR-0009). Hardware-backed key (Secure Enclave / StrongBox / TPM) = **high assurance**
  (revoke-device is final); **software-protected keystore** when no TPM = **standard
  assurance** (also needs a key-rotation path; device-revocation alone isn't final).
  Attestation at device-approval gate 1 is optional; assurance level recorded on the MLS leaf.

- **Org scope & visibility = #45 c–f resolved 2026-06-09 (TRUST_MODEL §3.2/§3.3).**
  (c) org is a first-class scope **above** workgroups; independent = implicit personal
  scope. (d) independent→org is **additive** — pre-existing personal workgroups **stay
  personal** (no org takeover). (e) hidden = **existence concealed even from the control
  plane** (blinded handles; ⚠️ carve-out from ADR-0010 "control plane sees all state" —
  the private-lookup/PSI mechanism is a follow-up ADR). (f) visibility is **layered**:
  org admin sets policy/caps, workgroup manager sets per-WG within bounds.

- **Identity keys = three tiers (ADR-0009, resolves #45 a/b/g).** Device + user +
  application **each** hold a distinct hybrid-PQ key (most granular). Chain
  user→device→app; revocation cascades down it. No plaintext key leaves a device
  (user/app keys are HW-sealed per device). Workgroups admit **devices, users, OR
  applications** as distinct member types. Open: user-key recovery ceremony.

- **Product tiers = packaging boundary (ADR-0008, features.md #49).** Individuals and
  **small business (< 12 devices/users)** run on **the Flutter client alone** — light
  manager actions (register/create/join/admit/revoke/basic grants) are in-client; the
  client is **"ridiculously cheap."** The **management console is a separate paid SKU
  ("extra $$")** — enterprise/org-scale only (fleet topology, org policy, audit, Ansible
  #46/#47). Ansible / fleet keys / org policy never ship in the client (that's the paid
  cutline). Exact pricing TBD (#49 clarify).

- **Runtime: Red Hat UBI container — UBI 10 by default, UBI 9 only where needed.**
  Refines the prior UBI-9 preference. "If needed" covers: a package not yet in UBI 10,
  or hardware that can't meet the RHEL 10 **x86-64-v3** baseline. The existing agent
  image (`agent/Containerfile`) is UBI-9 (verified arm64, commit `8a9d6a7`); migrating
  it to UBI 10 is a tracked follow-up needing an arm64 rebuild + the v3 caveat check.

- **Cache/store engine: Valkey (BSD-3), not Redis.** Redis relicensed to RSALv2/SSPL
  in 2024 (not OSI-open); Valkey is the Linux Foundation, wire/command-compatible fork.
  Use Valkey for the single source of truth. (ADR-0010, §13.)

- **Single source of truth = one distributed Valkey**, accessed **only behind the
  control-plane API** — GUIs never connect to the store directly (preserves ADR-0006
  zero-trust front door). Runs as a durable store (AOF + RDB + replication), not a cache.
  "Appropriate locks" = atomic CAS for coordination; **fencing tokens + MLS epoch
  ordering**, not Redlock, are the correctness boundary for security-critical mutations.
  (ADR-0010.)

- **GUIs have an OO domain-model layer; React/Vite (console) and Flutter (client) are
  rendering only.** Console = TS classes from `control-plane.openapi.yaml`; client =
  parallel Dart model from the same contract. No business logic in widgets. The client
  stays Flutter (ADR-0007/0008 preserved — *not* a React rewrite). (ADR-0010.)

- **Permissions are granular, OO, with inheritance and polymorphism.** A `Permission`
  base specializes (port / network-egress / mount / device / resource-quota /
  capability …); evaluation is polymorphic; grants inherit org → workgroup → device →
  application/task. Default-deny holds (feature #48). (ADR-0010 §1.)

## Security invariants (Eddie 2026-06-09 — governing, system-wide)

- **All data is encrypted at rest.** Every persistent store — including the Valkey
  source of truth, agent volumes, model stores, backups — is encrypted on disk. Keys are
  not co-located with the ciphertext. (Elaborate in `TRUST_MODEL.md`.)

- **Need-to-know at intermediate nodes.** Data is revealed to intermediate nodes (mesh
  relays, routers) **only on a need-to-know basis** — payloads stay end-to-end encrypted;
  a relay sees only the routing metadata it requires, never the cleartext it forwards.
  (Aligns with the existing envelope-encryption design; elaborate in `TRUST_MODEL.md`.)

- **Quantum-resistant cryptography throughout.** All cryptography (identity keys, key
  exchange, at-rest encryption keys, signatures) uses **post-quantum / hybrid-PQ**
  primitives — not classical-only. Consistent with the hybrid-PQ identity keys already
  in the trust model (liboqs). (Elaborate in `TRUST_MODEL.md`.)

- **Insecure transport is explicit opt-in, never a silent default** (post-demo
  tightening, 2026-06-10). `registry_scheme=http` fails fast at `load_config`
  unless `BARDPRO_ALLOW_INSECURE_HTTP=true` is also set, and even then logs a
  startup WARNING. The demo's plain-HTTP-over-Tailscale hop carries the opt-in
  in its `podman run` env.

- **Agent containers run baseline default-deny** (post-demo tightening,
  2026-06-10): non-root `bard` user in `agent/Containerfile`, no baked ssh host
  keys, sshd never started in MVP (openssh-server stays installed for v2 /
  ADR-0004), `EXPOSE 8444` only; demo `podman run` adds `--cap-drop=all`,
  `--security-opt=no-new-privileges`, `--read-only --tmpfs /tmp`,
  `--pids-limit=512`. The fine-grained SELinux per-task grant model (features
  #48) remains the v2/v3 roadmap on top of this baseline.

- **Reachability is outbound-first: broker link before any mesh** (v1.1.0,
  2026-06-10, ADR-0013 / features #59). Agents opt in
  (`BARDPRO_BROKER_ENABLED`) to a persistent outbound WS to the Router's
  `/v1/agent-link`; the Router dispatches down a live link first and falls
  back to the direct HTTP dial. Tailscale/Headscale stays an *option*, not a
  dependency. Broker frames are the additive
  `contracts/broker-link.schema.json`; link state is Router-process-local
  until the Valkey control plane (ADR-0010) shares it.

## Process / conformance

- **Conform to shared-rules** (Eddie 2026-06-09: "other rules as in shared-rules").
  The shared-rules document is Eddie's external cross-project standard; it is referenced
  in `CLAUDE.md` hard rule #1 (reconciled with shared-rules §0.10/§7.4). When shared-rules
  and a local rule conflict, surface it; Eddie overrides either way.
