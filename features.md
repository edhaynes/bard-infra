# bard-infra — feature backlog

Infrastructure features for the Bard zero-trust fabric. Format per
`shared-rules/process-rules.md §2`: each entry has a short description, date
added, and a status beginning with exactly one of `Open`, `In Progress`, or
`Completed`.

> **Two backlogs, one file.** The `INFRA-*` items below are the
> infrastructure-shaped features (DNS, transport, control plane, metrics). The
> **Fabric / platform backlog** at the bottom holds the verbatim product-fabric
> entries (`#60`–`#81`) migrated from the retired `bardLLMPro/features.md` when
> the fabric was re-homed into this repo (commit a9caafd). Their original
> numbers are preserved so the dense cross-references between entries (and from
> `bugs.md`) keep resolving; statuses are normalised to the
> `Open` / `In Progress` / `Completed` vocabulary.

## Infrastructure

### INFRA-1 — Fabric name resolution (DNS) so endpoints aren't pinned to IPs

- **Added:** 2026-06-13
- **Status:** Open
- **Type:** Infrastructure (not a plugin — *how the platform works*).

**Problem.** Fabric endpoints (Router, Registry, agents, the LokNet front
door) are addressed today by hard-coded `host:port` through the config layer.
When an address changes — DHCP lease, host reimage, cloud redeploy, tailnet IP
reassignment — every pinned reference breaks. Not hypothetical: on 2026-06-13
the `frogstation` GPU node was reimaged, its tailnet IP moved
`100.82.167.91 → 100.92.74.65`, and every config/SSH entry pinned to the old IP
went dead while the **name** `frogstation` kept resolving (Tailscale MagicDNS).

**Feature.** A name-resolution layer so every fabric participant is addressed
by a **stable logical name**, never a raw IP: clients reach the Router by name,
agents register/heartbeat under a name→endpoint mapping, and the public
Router/broker front door has a stable resolvable address that survives backend
IP churn.

**Options to evaluate (design-only):**
- **Mesh-native DNS** — Tailscale **MagicDNS** (already resolves the fleet by
  name today) or Headscale DNS. Cheapest; zero new infra; names stable by
  construction.
- **Registry-backed internal resolver** for the mesh-free **LokNet** path — the
  Registry already holds the authoritative node list; expose name→endpoint
  resolution from it so the broker front door and agents are reachable by name
  without a mesh.
- **Standard DNS / SRV records** for a public Cloud-Run Router front door
  (stable FQDN) so external clients never embed an IP.

**Done-signal.** Router/Registry/agent config accepts logical names; a node
whose IP changes rejoins and is reachable with **no config edit**; a test swaps
a node's address and asserts the fabric still resolves it.

**Decision (2026-06-15, Eddie).** MVP targets **MagicDNS-only** — lean on the
Tailscale MagicDNS that already resolves the fleet by name today (zero new
infra, names stable by construction). This is enough for the home/beachhead
profile. It does **not** cover the mesh-free LokNet path or a public-Router
FQDN; those (registry-backed resolver, managed DNS) are explicitly deferred,
and the longer arc is **self-hosting our own DNS** — see [INFRA-2](#infra-2--self-hosted-fabric-dns-target-state).
Resolves the former (a)/(b) clarifications. Re (c): name resolution sits
**beside** the bardLLMPro liveness/heartbeat work (#54, Completed), not on top
of it.

**MVP deliverable (this repo).** The config that must accept logical names
lives in bardLLMPro (`common/config.py`); the cross-repo wiring is a tracked
follow-up, not MVP. In bard-infra the MVP ships: the frozen name-resolution
**contract**, a startup **validator** (fail-fast when a logical name does not
resolve or a raw fabric IP is pinned), and an **IP-swap regression test**
proving a node that changes address stays reachable by name.

**Demonstrated live (2026-06-16).** The done-signal is met in practice: the
fabric was brought up across the tailnet (Mac + gx10 agents, `edwards-macbook-pro`
+ `gx10`), addressed **by MagicDNS name** with `ENFORCE_PEER_NAME_RESOLUTION=true`
— both registered and a client request **routed to the remote gx10 agent and back**
(echo) over the tailnet. During the same session Tailscale reassigned frogstation's
IP **twice** (re-auth) and **the name never changed**, so name-based access held
with zero config edits — exactly the IP-churn case INFRA-1 exists for. Reproduce:
`bardLLMPro/scripts/tailscale_fleet_up.sh edwards-macbook-pro gx10` +
[`docs/runbooks/tailscale-fabric-demo.md`](docs/runbooks/tailscale-fabric-demo.md).
The schemed-advertised-address validator gap this surfaced is fixed in
bardLLMPro `2f369bf`.

### INFRA-2 — Self-hosted fabric DNS (target state)

- **Added:** 2026-06-15
- **Status:** Open
- **Type:** Infrastructure (post-MVP evolution of INFRA-1).

**Want (Eddie, 2026-06-15):** "eventually want our own dns." MagicDNS is the
MVP because it is zero-infra, but it ties name resolution to Tailscale. The
target state is a fabric-owned resolver so names work on the mesh-free LokNet
path and for a public Router front door, independent of any single mesh
provider. Candidates carried forward from INFRA-1's deferred options: a
**registry-backed internal resolver** (the Registry already holds the
authoritative node list) and/or **managed/standard DNS** (Cloud DNS, Route53,
or self-hosted authoritative) for a stable public FQDN. Design-only until the
MVP lands; sequenced after INFRA-1.

**Design frozen (2026-06-24, Jason — see `plans/PLAN_mesh_decoupling.md`).** A
code trace established that Tailscale coupling is shallow: only `SystemResolver`
(name plane, behind the `Resolver` ABC) and L3 reachability. Bard's transport is
L7 (`wss://`/`httpx`), so the mesh's wire protocol is irrelevant. Plan: a
`RESOLVER_BACKEND` selector + a `RegistryResolver` (registry-backed name plane =
INFRA-2 core), with **Nebula** (slackhq, MIT, ARM64-native, no control plane to
host) as the pluggable L3 substrate below Bard. Runner-up Headscale rejected
(chases Tailscale's proprietary protocol). LokNet (INFRA-3) is the already
mesh-free agent path. Tailscale demoted to a dev convenience.

## Migrated from bardLLMPro — canonical infra index

These items are implemented or decided in bardLLMPro; their authoritative
source (ADR / CHANGELOG / contract) lives there. This repo is the canonical
**index**: each entry carries the reconciled status and a source pointer, not a
copy that can drift. (A1 migration reconciled 2026-06-15; the six former
`(migrate)` placeholders are now dated entries below. Source: bardLLMPro at
`~/projects/bard-llm/bardLLMPro/`, frozen contracts under `contracts/`.)

### INFRA-3 — LokNet outbound-agent broker transport

- **Added:** 2026-06-15 · **Status:** Completed (bardLLMPro v1.1.0–v1.3.0)
- **Source:** bardLLMPro #59; ADR-0013; `contracts/broker-link.schema.json`.

Agents hold a persistent **outbound** WebSocket to the Router (`/v1/agent-link`),
so the fabric needs a single public TLS front door and no mesh, port-forwarding,
or inbound agent ports. Slice 1 (frameId-correlated `/infer` dispatch over WS),
slice 2 (registration + heartbeat relay to a private Registry), and slice 3
(Cloud Run deploy recipe) are all done; real-socket smoke test proven (v1.2.1).
Agent opt-in: `BARDPRO_BROKER_ENABLED=true` + `BARDPRO_BROKER_URL=wss://<router>/v1/agent-link`.

### INFRA-4 — Quay image distribution

- **Added:** 2026-06-15 · **Status:** Open (v2; CI/infra, no frozen design yet)
- **Source:** bardLLMPro #53; tied to the weekly UBI rebuild pipeline.

Multi-arch (amd64 + arm64) agent images published to and pulled from Quay, with
Clair vulnerability scanning and cosign signing in the pipeline. Today images
build locally (UBI-9 Podman); the Quay distribution + signing path is designed
but not built. Sequenced for v2.

### INFRA-5 — Valkey control plane

- **Added:** 2026-06-15 · **Status:** Open (v2; deferred decision)
- **Source:** bardLLMPro ADR-0010 (Proposed, deferred to v2); ROADMAP "Walk" tier;
  `contracts/control-plane.openapi.yaml`.

Replace the single-instance JSON-file Registry store with **Valkey** (Apache-2.0
Redis drop-in) as the source-of-truth KV + pub/sub: enables multi-instance
Router/Registry (HA), a LokNet dispatch queue, and persistent agent/device
records. The single-front-door design (Router public, Registry private) depends
on this. Not started; gates multi-instance HA.

### INFRA-6 — Ansible config-management facts

- **Added:** 2026-06-15 · **Status:** Open (enterprise/v2 roadmap; no design yet)
- **Source:** bardLLMPro MEMORY.md (enterprise-only; never ships in the client).

Treat config-management **facts** as infrastructure (host/fleet state), distinct
from any playbook-automation *plugin* that would run on top of the fabric. An
enterprise-profile (Profile B) item; flagged but not designed. Sequenced after
the control plane.

### INFRA-7 — Prometheus metrics + structured logs

- **Added:** 2026-06-15 · **Status:** Completed (bardLLMPro v0.12.0)
- **Source:** bardLLMPro #55; `prometheus-client` 0.25.0.

Unauthenticated `/metrics` (Prometheus format) on Router, Registry, and Agent;
structured JSON logs via `BARDPRO_LOG_FORMAT=json` (default json). Satisfies
rubric dimension 8 (observability) for the shipped fabric.

### INFRA-8 — Registry agent liveness (heartbeat + TTL)

- **Added:** 2026-06-15 · **Status:** Completed (bardLLMPro v0.11.0)
- **Source:** bardLLMPro #54; `contracts/registry.openapi.yaml`.

Agents heartbeat `POST /register` on an interval (`BARDPRO_HEARTBEAT_INTERVAL_S`,
default 15s); the Registry stamps `last_seen` and marks an agent stale past its
TTL (`BARDPRO_AGENT_TTL_S`, default 45s), excluding stale agents from `/pool`
and `/schedule`. INFRA-1 name resolution sits **beside** this, not on top of it.

## Fabric / platform backlog

Verbatim product-fabric backlog migrated from the retired `bardLLMPro/features.md`
(re-home commit a9caafd, 2026-06-18). Original `#` numbers preserved (entries and
`bugs.md` cross-reference each other by these numbers); the `Status` column is
normalised to `Open` / `In Progress` / `Completed`. The pre-split history is
frozen at tag `archive/pre-infra-split-2026-06-18` in bard-llm.

| # | Description | Date | Status |
|---|---|---|---|
| 60 | **Pro: distributed NAS — pool stranded *storage* across home nodes (Eddie 2026-06-10)** — generalize the fabric's thesis from stranded *compute* to stranded *storage*: pool idle disk across the home power user's boxes (desktop, NAS, old server) into one distributed store. **Honest scoping (Jason):** this is a NEW stateful workload class, distinct from the stateless inference dispatch the fabric is built on — needs replication, consistency, a storage protocol (NFS/SMB/S3-compatible), durability + encryption-at-rest (ties to TRUST_MODEL v3 + the coding-rules storage-adapter abstraction). The discovery seam isn't there yet: `power-profile.schema.yaml` advertises cpus/memory/gpus/pidsLimit but **no storage field**. Sequencing: NOT first-MVP (that's compute: LLM-proxy + remote-access + pool/place); position as the **headline v2 storage expansion**. First brick (small): add `storage` to the power profile so nodes advertise free disk. The NAS itself is a large follow-on (likely wrap/integrate MinIO/SeaweedFS/Garage rather than build a filesystem — §13 dependency review). <br>Clarify: object (S3) vs file (NFS/SMB) first? build-vs-integrate an existing OSS store? part of the "ad-hoc home" Profile A or the managed Profile B? | 2026-06-10 | Open — v2 expansion |
| 61 | **Pro+relay: Claude & ChatGPT agent backends behind the InferenceEngine seam (Eddie 2026-06-10)** — claudeTalk originally connected to Claude agents (relay `agent_claude.py`, Claude Agent SDK). Bring that to the **product fabric** and add the **OpenAI/ChatGPT** counterpart: two new swappable `InferenceEngine` backends (Claude via Anthropic API/Agent SDK; OpenAI via its SDK/agents) joining echo/llamacpp/vLLM(#51). A fleet agent node can then be local llama.cpp OR a proxy to Claude OR to ChatGPT; `/schedule`+capabilities route. Agentic: protocol already carries `toolCalls`/`toolResults`, so tool-using loops surface natively. Relay: add an `agent_openai.py` mode beside `agent_claude.py`. **Honesty (Jason):** cloud agents egress prompts to Anthropic/OpenAI — this BREAKS Profile A's "nothing leaves your network" for those requests, so it must be a labeled per-workload OPT-IN (local-by-default, frontier-on-demand), not the default; surfaces in SECURITY_AND_INTEGRATION.md. Keys via config/Secret Manager, user-supplied, never bundled (§13: anthropic + openai SDKs are new deps — review). **Impl note:** the agent that builds the Claude backend MUST consult the `claude-api` skill for current Claude model IDs + Agent SDK usage (do not hardcode from memory). <br>Clarify: chat-completion parity first, or full agentic (tools) from the start? per-request backend selection (client picks model) vs per-agent-node? Profile A opt-in only, or both profiles? | 2026-06-10 | Open |
| 62 | **Pro: robust AI-backend availability — active readiness + automatic failover (Eddie 2026-06-10)** — make "is the backend up?" robust, not best-effort. Have today (discovery half): heartbeat/TTL liveness (#54) excludes dead nodes from pool/schedule, LokNet broker auto-reconnect, `502 agent_unavailable retry:true`. Missing (reactive half): (a) **active readiness probing** — verify the agent's model actually loads + answers (a real inference probe), not just `/healthz`=200, and gate placement on ready-not-just-alive; (b) **automatic failover** — when the scheduled node is down/unready, the Router re-places onto another capable node (GPU-preferred, CPU-fallback) instead of returning 502 to the client; (c) optional circuit-breaking + client-visible backend status. Reliability hardening for Profile A (home power user). <br>Clarify: how many failover retries before surfacing an error? readiness probe cadence + cost (a real token gen is expensive — cache the result)? expose a `/ready` distinct from `/healthz`? | 2026-06-10 | Open |
| 63 | **Pro: Ollama backend + discover/bridge disconnected Ollama instances (Eddie 2026-06-10)** — homelab users already run Ollama everywhere; bring them into the pool. Two parts: (a) an `OllamaEngine` `InferenceEngine` backend talking to the Ollama HTTP API (the relay already has an `ollama` mode — port it to the fabric; Ollama is the coding-rules default local LLM); (b) **auto-discover + bridge standalone Ollama servers** on the LAN that aren't formally fleet agents — the concrete first consumer of the ADR-0014 Profile-A LAN-discovery (mDNS/Bonjour) open decision — presenting each as a fabric agent advertising its installed models. "Disconnected" = tolerate Ollama nodes that come/go (laptop sleeps, model cold) and wake/route on demand — leans on #62 robustness. <br>Clarify: discovery via mDNS vs config list vs scan a CIDR? advertise each Ollama *model* as a capability, or the node with a model list? wake cold models (Ollama loads on request) or only route to loaded ones? | 2026-06-10 | Open |
| 64 | **Pro: management console — Tailscale-style device enrollment, but private (Eddie 2026-06-12)** — a web console where you add devices to your fleet the way Tailscale adds nodes (enroll, name, approve, see status/capabilities, revoke), except the control plane is YOURS: self-hosted, no third-party coordination server, nothing leaves the network (Profile A posture; aligns with the existing LokNet outbound-only broker so enrolled devices need no inbound reachability). Building blocks already exist: `clients/console/` React stub with typed topology model, `contracts/control-plane.openapi.yaml`, `contracts/trust.schema.yaml` (orgs→workgroups→devices), power-profile capability advertisement, Registry liveness. Gap is the wiring: device-enrollment flow (join token / QR like Tailscale), approval queue, revocation (JWT per-device instead of fleet-wide shared secret — also closes the bug #56/#54 class properly), live status from Registry heartbeats. Recon estimate: 2–3 week build for Profile B-lite. <br>Clarify: enrollment UX — join-token paste, QR scan, or LAN auto-discover + approve (ties to #63 mDNS decision)? Is per-device JWT/key rotation in scope for v1 of the console (recommended — fleet-wide shared secret is the audit's standing weakness)? Does Profile A get a read-only console too, or is console = Profile B only? <br>B5 read-only slice shipped 2026-06-12 (branch sprint-b5-console-readonly): `GET /fleet` contract + Registry route, console renders real device list / heartbeat status / capabilities / workgroup grouping, Playwright structural suite. <br>B6 manage slice shipped 2026-06-12 (branch sprint-b6-console-manage, v1.5.5): approve/revoke/rename/workgroup-assign from the console (contract-first: control-plane rename/workgroup/audit paths + additive `DeviceRecord.workgroup`), append-only audit log (`registry/audit_log.py`, `GET /audit`, console Activity pane), one-time device code surfaced at approval, full enroll→approve→serve→revoke loop proven on real sockets in `scripts/smoke_console_manage.py`. Remaining before Completed: Eddie's visual sign-off (screenshots — §14) and the merge ruling on the `claude/laughing-bell-57o15u` range. | 2026-06-12 | In Progress |
| 65 | **Pro: plugin manager in the console — install/enable/configure plugins, Squawk Box first (Eddie 2026-06-12)** — the console (#64) gets a "Plugins" pane: browse the catalog (Squawk Box walkie-talkie, SSH/SCP, remote desktop — the ROADMAP v2 SDK list), enable per-device or per-workgroup, configure, see health. Squawk Box (the Maude walkie-talkie client presented as the first plugin) is the proving case for the plugin seam — also the eds-rules book capstone worked example (F7 there), so the contract shown in the book and the one the console manages MUST be the same seam, not parallel inventions. Depends on: #64 console wiring + the v2 plugin SDK (ADR-0007/0012). <br>Clarify (answered at B8 pickup, Powell calls): plugin distribution = **bundled-only at first** — the catalog loads from a local manifest dir (`BARDPRO_PLUGIN_CATALOG_DIR`), no third-party install path, no supply-chain surface; a signed-package format is future work. Per-plugin permissions model = **deferred to TRUST_MODEL v3** (the manifest's `requiredCapabilities` is declarative matching, not enforcement). <br>B7 shipped 2026-06-12: frozen `contracts/plugin-manifest.schema.json` (the eds-rules book capstone seam) + Squawk Box and SSH example manifests. <br>B8 shipped 2026-06-12 (branch sprint-b8-plugin-manage, v1.5.6): control-plane plugin surface (`GET /plugins`, enable/disable per device/workgroup, per-target config validated against the manifest's configSchema, reported health on the heartbeat pattern), `registry/plugin_store.py`, console Plugins pane (toggle + schema-driven settings form + collapsed Advanced JSON + plain-words health), plugin actions audited, `scripts/smoke_plugin_manage.py` 8/8 PASS. SSH is the second catalog entry; the SSH *service itself* stays ROADMAP Sprint 5. Follow-ups: requiredCapabilities filtering of offered targets in the pane; plugin *launching* (manifest `entry`) — enablement today is desired state. Remaining before Completed: Eddie's visual sign-off (screenshots — §14). | 2026-06-12 | In Progress |
| 66 | **Squawk Box: squelch for noisy work environments (Eddie 2026-06-12)** — a squelch control on the walkie-talkie plugin so a jobsite (compressors, saws, traffic) doesn't keep the channel open on ambient noise. Classic VOX squelch: gate transmission/playback below a configurable noise floor; threshold per-user, maybe auto-calibrating to the ambient level. Pairs with the construction-crew use case (#67). <br>Clarify: squelch on the SENDER (don't transmit below threshold — saves bandwidth/relay) or RECEIVER (don't play below threshold) or both? Auto-calibrate vs manual dial? Push-to-talk as the alternative for very loud sites? | 2026-06-12 | Open |
| 67 | **Squawk Box: construction-SMB onboarding — fewest clicks to invite a crew (Eddie 2026-06-12)** — the headline persona: a construction small-business owner who wants walkie-talkies for his teams. The product wins or loses on how fast he can invite his workers to a new Squawk Box channel. This is the SAME UX problem as Bard device enrollment (sprint B3 "the Tailscale moment") — converge them: one invite primitive (join token / QR / SMS link) serves both "add a device to the fleet" and "add a worker to a channel". Target: minimize clicks from "I want a channel" to "my crew is talking." Linda researching the persona + the minimal-invite-click benchmark vs competitors (Zello, Voxer, two-way radio). <br>Clarify: workers install an app first (app-store friction) or join via a link with no account? Owner-paid seats vs per-worker signup? Is the channel ephemeral (jobsite-duration) or persistent? | 2026-06-12 | Open |
| 68 | **Squawk Box: red "recording/live" warning indicator (Eddie 2026-06-12)** — a prominent red light/icon shown whenever the channel is live-transmitting or recording, so everyone in earshot knows the mic is hot. Consent/privacy (two-party-consent states; jobsite bystanders). Show on the sender's device while transmitting and on the channel view when any member is recording. <br>Clarify: does Squawk Box RECORD (store audio) or only live-relay? If it records, retention + who-can-play-back is a privacy feature of its own. Red icon on transmit (always) vs only when persisted-recording is on? | 2026-06-12 | Open |
| 69 | **Pro: B2 per-device identity foundation (ADR-0010, pragmatic JWT-class)** — replace the fleet-wide shared `BARDPRO_JWT_SECRET` (one secret signs+verifies every agent — bug #54/#56 class) with per-device credentials issued through an enrollment lifecycle (join-token → pending → active → revoked), each device holding its OWN HMAC signing key. Opt-in (`BARDPRO_DEVICE_IDENTITY_ENABLED`, default false) so v1.x fleet-JWT deployments keep working. Contract: `contracts/enrollment.schema.json` (FROZEN). Implements `PerDeviceVerifier` (resolves the device's key by deviceId — the seam where asymmetric/PQ slots in for v3, NOT implemented here), `DeviceStore` (JSON persistence parallel to agents), Registry `/enroll` `/devices` `/devices/{id}/approve|revoke`, and the agent per-device mint path. This is the foundation the console (#64, B5/B6) and relay auth (B4) build on. NOT the v3 PQ/MLS trust fabric. <br>Clarify: should management endpoints (`/devices*`) move to per-device manager creds too, or stay on the fleet/admin JWT (current)? join-token delivery — paste/QR/SMS (converges with #67)? key rotation cadence for active devices? | 2026-06-12 | Completed 2026-06-12 — B2 foundation (ef5435c, ships in v1.5.3) + B4 Router relay enforcement (v1.5.4); clarify items roll to #64 console work |
| 81 | **Pro: B3 channel invites — one-click link/QR redemption, no account (backend)** — the "send a link, click, you're in" flow (Eddie: SMB owner texts/emails a link or QR; worker clicks; the channel box appears; they're talking in hands-free PTT). Backend shipped: `contracts/invite.schema.json` (FROZEN 2026-06-12), `ChannelStore` (single-use expiring invite JWTs aud `bard-channel-invite`, JSON persistence, injectable clock), `DeviceStore.admit` (one-step ACTIVE admission — the owner pre-authorized by sending the link; contrast fleet enroll→approve which is unchanged), Registry `POST /invites` (manager-authed), `POST /invites/{token}/redeem` (no bearer — the link IS the authorization), `GET /channels/{id}/members`. QR rendering is client-side (the inviteUrl is the QR payload — no new dependency). **Remaining (out of backend scope): the mobile redemption UI** — open link → channel box appears → hands-free PTT — lands in the Maude/claudeTalk app (converges with #67); needs its own sprint + handoff. | 2026-06-12 | Completed 2026-06-12 (backend, v1.5.3) — mobile UI Open, see #67 |
| 82 | **Pro: S6 box ping — cross-device signal over the box (ADR-0016 / `PLAN_device_identity_mvp.md`)** — a channel member pings the box and every OTHER member with a live connection receives it; the MVP's cross-device payoff (voice/LiveKit is out). Backend shipped (this entry): Router `POST /channels/{channelId}/ping` (FleetOrDeviceVerifier-authed; caller MUST be a member → 403 otherwise; sender excluded; returns `{delivered, offline}`), a one-way push rail on the broker (`BrokerLink.send_json` + `BrokerLinkManager.send` — fan-out with no reply, distinct from request/reply `dispatch`), the `box.ping` frame added to `contracts/broker-link.schema.json`, the ping path + `PingResponse` added to `contracts/router.openapi.yaml`. Device receive-links register on the existing `/v1/agent-link` keyed by deviceId (the device's own EdDSA token, accepted by FleetOrDeviceVerifier). Router builds a read-only `ChannelStore` (`reload_on_read`) over the Registry's channel-state file for the membership gate. **Remaining (out of backend scope): the Flutter client** — receive-link + ping UI lands in the app (parallel worktree `feat/s6-flutter-ping`); §14 on-device sign-off is S8. | 2026-06-18 | Completed 2026-06-18 (backend, feat/s6-box-ping) — Flutter client + sign-off pending |
| 83 | **Pro: S7 recovery — two-tier seed escrow (Flutter client, ADR-0016 §5 / `PLAN_device_identity_mvp.md`)** — the client side of recovery. **Prerequisite refactor shipped:** the deviceId is now DERIVED from the public key (`deriveDeviceId` = `"dev-" + crockford(sha256(pubKey)[:10])`, `clients/app/lib/box/crockford.dart`) instead of random/time-seeded, so recovering the seed reproduces the SAME deviceId and box memberships survive. **Recovery shipped:** the 32-byte identity seed is wrapped TWICE — under the app password and under a one-time OMG code (Crockford base32, 3×5, e.g. `7K3P9-R2M4X-WQ8TB`) — via Argon2id→AES-256-GCM (`SeedWrapper`, blob = `salt++nonce++ct++mac`, base64; `cryptography` dep, Apache-2.0, pure-Dart/ARM-clean). Frozen contract wired in `BardApi`: `POST /recovery/escrow` (device-token, `{handle, publicKey, wraps:{password, omg}}`) + `GET /recovery/escrow/{handle}` (no-auth → `{publicKey, wraps}`). `RecoveryController` orchestrates first-run escrow + fresh-install recovery (fetch→unwrap→`restoreFromSeed`→self-register, memberships restored). UI: the OMG one-screen (show-once + wipe-on-confirm), the escrow-setup screen, the recover screen (password OR OMG toggle), entry points on the Box onboarding. The seed/password/OMG plaintext never leave the device. Tests: 90 client tests green (wrap/unwrap round-trips, deviceId determinism, escrow POST/GET wiring, OMG format/normalize, full escrow→recover identity reconstruction, recovery UI); `flutter analyze` clean. **Remaining:** the backend zero-knowledge escrow store is the parallel worktree `feat/s7-recovery-escrow`; §14 on-device sign-off is S8. | 2026-06-18 | Completed 2026-06-18 (Flutter client, feat/s7-flutter-recovery) — backend escrow + sign-off pending |
| 84 | **Pro/client (box): name your own device — friendly device names** — users name their device (default "iPhone"/"iPad"); on first registration a "Name this device" dialog binds a friendly `label` to the opaque `dev-…` deviceId, shown everywhere instead of `dev-blah`, plus a rename action. The backend already carries a `label` field on every device record. | 2026-06-18 | In Progress — frontend agent on branch `feat/device-naming`; parked, not integrated (document-don't-fix-on-the-fly, Eddie 2026-06-18). |
| 85 | **One Bard app, capabilities as plugins; MVP = Box-first** (Eddie 2026-06-18) — the bard-infra client is ONE app ("Bard") = the shell; LLM/Chat/Terminal/SSH/Squawk Box are PLUGINS added to it. The current MVP is the **Box only**; the legacy Pro-client tabs (Dashboard/Connections/Terminal/Chat/Models) are out of scope — don't fix unrelated breakage. Proposed: trim the MVP build to **Box-first** (hide the legacy tabs) so broken legacy surface isn't reachable; plugins return as real plugins later. | 2026-06-18 | Open — scope decision; the Box-first trim is pending Eddie's go. |
| 86 | **Pro/client (recovery): private recovery-key QR — "DO NOT SHARE"** (Eddie 2026-06-18) — present the recovery key (the user-seed / OMG code) as a QR labeled **"PRIVATE — DO NOT SHARE"** the user can photograph/screenshot for safekeeping (a visual complement to the typed OMG code). The recover flow can also **scan** it (camera) to restore. Distinct from the PUBLIC identity QR (shareable). | 2026-06-18 | Open — folded into the ADR-0017 user-key recovery work (sprint U3). |
| 87 | **Docs: current-architecture doc + reconcile stale historical docs** (Eddie 2026-06-18) — at the next stop, write a single accurate current-architecture doc and bring stale docs up to date (ADR-0016 now superseded by 0017; PLAN_device_identity_mvp describes the old device-only model; READMEs/ADRs post the repo-split + S1–S7 + user+device shift). | 2026-06-18 | Open — scheduled for the next stop. |
| 88 | **Fabric: TSN (Time-Sensitive Networking, IEEE 802.1) transport — deterministic dispatch (Eddie 2026-06-24)** — eventual integration so the fabric can dispatch inference over **deterministic, bounded-latency** transport, carrying the on-prem determinism thesis down to the wire (fits the RTOS/avionics determinism lineage). Lands at the name-resolution + transport seams (`bard_infra/nameres/resolver.py`, the agent/router transport layer) — a TSN-aware path selected for latency-critical workloads, best-effort otherwise. Honest scoping (Jason): TSN needs 802.1Qbv/Qav-capable NICs/switches + time sync (802.1AS/PTP) — a hardware-gated, niche capability, NOT a software-only feature; position as a **"Run"-horizon** differentiator, not MVP. No design yet. <br>Clarify: which TSN class first (time-aware shaping vs credit-based shaping)? hardware target (which NICs/switches in the testbed)? does it ride Tailscale/MagicDNS addressing or require a parallel L2 fabric? | 2026-06-24 | Open — horizon (v3 "Run"); no design yet |
| 89 | **Fabric: assess OpenZiti as the connectivity fabric / transport (Eddie 2026-06-24)** — evaluate OpenZiti (openziti/ziti, NetFoundry, **Apache-2.0**) as a candidate transport, a **third option vs the D5 decision** (TRUST_MODEL §10.1: official Tailscale / self-host Headscale). Fit thesis: OpenZiti is an **application-layer zero-trust overlay** (vs Tailscale's network-layer WireGuard mesh) — identity-based, mTLS per connection, **outbound-only with "dark" services** (services don't listen on the network; reachable only through the fabric), and an **embeddable SDK** (C/Go/Swift/Kotlin/…). The outbound-only/dark-service model maps directly onto Bard's **LokNet outbound-broker** design — OpenZiti could *be* the broker rather than hand-rolling it on Cloud Run (bears on the parked cross-network coordinator deploy). Cross-connect: the **C SDK** is also relevant to the Anunix zero-trust-networking module. Trade-off: heavier to operate than Tailscale (controller + edge routers), larger conceptual surface; ARM builds exist. This is an **evaluation/architecture decision, NOT a live pivot** — does not block the device-only four-client join (LAN/localhost dev transport). Linda due-diligence + a Claudius design call; touches recorded decision D5. <br>Clarify: replace Tailscale/Headscale (D5) or sit alongside as a third pluggable transport? embed the SDK in the agent/client or run tunnelers? does it subsume the LokNet broker + the Cloud Run coordinator, or layer over them? MLS/identity layer (TRUST_MODEL §3–§9) stays on top regardless — confirm. | 2026-06-24 | Open — evaluation; no design yet |
