Status: Partial — Lanes A–F all built (2026-06-07): server MVP runs end-to-end on macOS TLS + UBI-9 container verified on arm64; Flutter client (Win/Android/macOS/Linux/iOS) builds to a macOS binary, analyze clean, widget test green; Lane E CI authored (parked in ci/). Remaining: ADRs, wire client→Settings config, post-MVP trust layer

# Bard — Design & Parallel Execution Plan

> Purpose of this doc: define the MVP architecture **and** carve it into independent
> workstreams with frozen interfaces, so multiple Claude agents can build in parallel
> without colliding. If you are an agent picking up work, read §1–§3, then go straight
> to your lane in §6. Do not touch another lane's files.
>
> **Scope authority: `ROADMAP.md`** (crawl/walk/run tiers + sprints) sits above this doc.
> Forks locked there (Eddie 2026-06-09): MVP inference = **llama.cpp in the agent**; **ssh
> CLI tab and remote spawn are v2, not MVP**; registry = **JSON-file** (Valkey is v2); the
> trust layer (`TRUST_MODEL.md`, ADR-0006…0010) is **v2/v3 direction, not MVP**. Client
> platform priority: **macOS + iOS first, designed to run on Windows + Linux** (ADR-0005).

---

## 1. What this is (and isn't)

Bard is a **separate project** from the consumer iOS app (the `bard-llm` repo /
"Bard LLM"). It **inherits** the engine/API/CLI lineage of that app — llama.cpp inference,
the OpenAI-compatible HTTP surface, the terminal — but is its own repo, its own
versioning/CI, and an **enterprise / professional** look-and-feel: a clean model **list**
(no album-cover art, no phonograph/cassette skins).

Server-side it is a small distributed system: a **Router** dispatches JSON requests to
**Agents** (UBI-9 Podman containers, or native sidecars) discovered through a **Registry**,
over TLS with JWT auth. A **Talk Service** adds text/voice on top of the same routing.

This doc currently lives inside the `bard-llm` repo (`bardLLMPro/`) while
incubating. Once code lands it splits into its own GitHub repo (see
`project_bard_llm_pro` memory).

---

## 2. Scope reconciliation (authoritative)

The three source docs (`BARD_LLM_PRO_ARCHITECTURE.md`, `_MVP_SPEC.md`,
`_TALK_INTERFACE.md`) disagree on scope. **This doc is the tiebreaker for MVP.**

| Question | MVP decision | Deferred to later |
|----------|-------------|-------------------|
| Mesh | **No Tailscale.** Direct TLS over LAN/Tailscale-IP if present. | Tailscale / Headscale / Nebula mesh, NAT traversal. |
| HA / distributed state | **Single-instance** registry, JSON-file persistence. | etcd/Consul, redundant routers, fail-over. |
| Voice | **Text only** in MVP. Talk Service ships with a `type:"text"` path; `voice` returns `501`. | STT/TTS sidecars, on-device Whisper. |
| Client platforms | **One cross-platform GUI codebase → Windows, Android, macOS, Linux, iOS.** Simple/professional UI built from the framework's official templates; **moves off Swift/SwiftUI** to escape the consumer app's recurring bug class. Framework: §8(g), recommend Flutter. | Per-platform native polish, tablet-specific layouts. |
| Local Podman support | **Where the OS allows it:** Linux (native), macOS/Windows (Podman Desktop Linux VM). These hosts run agent containers locally **and** can be the *remote* target for thin clients (#41). | — |
| Containers on iOS/iPadOS | **Not possible — iOS is a client only.** No Linux kernel, no namespaces/cgroups, sandbox forbids it, no background daemon; iSH is a userspace emulator and can't host a runtime; iOS 17+ gives no third-party hypervisor. iOS reaches containers **remotely** (#41) and/or runs a **native on-device agent** (llama.cpp + Metal/CoreML) exposing the *same* OpenAI-compatible API **without a container**. Strike all iSH-runs-the-container claims. | Native on-device inference *agent* (endpoint, not a container). |
| HW accel | **NVIDIA on Linux** via NVIDIA Container Toolkit (`--gpus all`). | macOS CoreML sidecar, Apple Neural Engine. |
| Remote compute | **Yes — core to Pro.** A thin client/router offloads to a **remote host's** resources: start/stop the UBI-9 Podman agent there and reach an LLM API served *from that container* (llama.cpp/vLLM behind the OpenAI-compatible surface) over TLS+JWT. MVP: **explicit remote host** + remote lifecycle via the agent's spawn endpoint and/or Podman remote API. (features.md #41.) | Capability/load-based scheduling, autoscaling, multi-host pools. |
| Routing backend | **LiteLLM** as the routing library. "Athena vLLM" is an *inference backend* reachable through LiteLLM, not a second router. | Custom cost/latency policy engine. |

Known defects in the source docs, fixed here: the duplicated High-water-mark paragraph
(arch doc lines 36–41) is dropped; the iOS-container contradiction is resolved in favor
of "client only."

---

## 3. Architecture (MVP)

```
                         ┌──────────────────────┐
   iOS app (client) ───► │   Router / Talk Svc   │ ──► Registry (agentId → host:port)
   CLI tab (ssh) ──┐     │  FastAPI, TLS + JWT   │
                   │     └───────────┬──────────┘
                   │                 │ TLS + JWT, JSON protocol
                   │                 ▼
                   │        ┌──────────────────┐
                   └──ssh──►│  UBI-9 Podman     │  llama.cpp / LiteLLM target,
                            │  Agent (+ sshd)   │  sshd for the CLI tab,
                            │  --cpus/--memory  │  openssh-clients for outbound hops
                            └──────────────────┘
```

- **Protocol**: one JSON envelope (`id`, `type`, `content`, `metadata{targetAgent,
  sessionId, timestamp, authToken}`) → response echoes `id`, may carry
  `toolCalls`/`toolResults`. This is the single most-shared artifact — see §4.
- **CLI tab transport**: the in-app terminal is an **ssh client** attaching to `sshd`
  inside the UBI-9 agent (key-based, app holds a key). The image also ships
  `openssh-clients` so a user can ssh *outbound* from the prompt. (features.md #38.)
- **Resource limits**: `--cpus`, `--memory`, `--pids-limit` from a YAML high-water-mark
  config the Router reads when spawning an agent. (features.md, FR-8.)

---

## 4. Contract-first: the freeze that unlocks parallelism

Parallel agents collide on **shared boundaries**, not on isolated code. So **Phase 0**
freezes every boundary as a committed artifact before any lane starts. Once these exist,
each lane codes against the contract — not against another lane's in-progress code.

The frozen artifacts (Phase 0 deliverables, one short serial task):

| Artifact | File | Consumed by lanes |
|----------|------|-------------------|
| **Wire protocol** JSON Schema (request/response, error shape `{error,retry}`) | `contracts/protocol.schema.json` | A, B, C, D, E, F |
| **Registry API** OpenAPI (`POST /register`, `GET /agents/{id}`, `GET /agents`) | `contracts/registry.openapi.yaml` | A, B |
| **Router/Talk API** OpenAPI (`POST /v1/message`, `/healthz`, `/version`) | `contracts/router.openapi.yaml` | A, C, F |
| **Agent API** OpenAPI (`POST /infer`, `/healthz`) | `contracts/agent.openapi.yaml` | A, B, C |
| **Power-profile** YAML schema (`cpus`, `memory`, `pidsLimit`, `gpus`) | `contracts/power-profile.schema.yaml` | B, D |
| **Repo layout + config layer** stub (`config.py`: env→.env→file→flag) | `common/` | all (imported, not edited) |
| **Fakes**: `FakeRegistry`, `FakeAgent`, sample JWT, self-signed test certs | `tests/fakes/` | A, C, F |

Rule for agents: **you may read every contract; you may edit only your lane's files.**
If a contract is wrong, you do **not** patch it in your lane — you stop and flag it so
the change is made once, in `contracts/`, and re-propagated. (CLAUDE.md §14: never
silently change scope.)

---

## 5. Repo layout (target)

```
bardLLMPro/
├── contracts/        # Phase 0 — frozen schemas (OpenAPI, JSON Schema, YAML)
├── common/           # config layer, JWT verify, TLS helpers, protocol models (shared, import-only)
├── router/           # Router + Talk Service (FastAPI)        ← Lane A
├── registry/         # Agent Registry service                ← Lane B
├── agent/            # Containerfile, agent HTTP server, sshd ← Lane C
├── scripts/          # run_agent.sh / .ps1, cert-gen, model-fetch ← Lane D
├── ci/               # GitHub Actions, podman buildx multi-arch ← Lane E
├── clients/app/      # Flutter client: CLI-tab ssh + Pro list UI (Win/Android/Mac/Linux/iOS) ← Lane F
└── tests/            # fakes + per-lane unit tests (each lane owns its subdir)
```

---

## 6. Parallel workstreams

Six lanes. Each names the files it **owns**, the contracts it **depends on**, and a
**done signal** the agent can verify alone. Lanes touch disjoint directories, so they
run concurrently after Phase 0.

### Lane A — Router + Talk Service  (`router/`, `tests/router/`)
- **Build**: FastAPI app: `POST /v1/message` validates JWT → looks up `targetAgent` in
  Registry → forwards over TLS to agent `/infer` → relays JSON. `voice` → `501`.
  Structured error `{error:"agent_unavailable", retry:true}` on unreachable agent.
  `/healthz` + `/version` (vX.Y.Z + sha + date, CLAUDE.md §11).
- **Depends on**: `protocol.schema.json`, `router.openapi.yaml`, `registry.openapi.yaml`,
  `agent.openapi.yaml`. Uses `FakeRegistry` + `FakeAgent` — **does not** need real
  Registry/Agent code.
- **Done signal**: unit tests green against fakes; `POST /v1/message` round-trips a text
  request; JWT-reject path returns 401; unreachable-agent returns the error envelope.

### Lane B — Agent Registry  (`registry/`, `tests/registry/`)
- **Build**: in-memory `agentId → host:port` map, JSON-file persistence on shutdown/load
  on start. `POST /register`, `GET /agents/{id}`, `GET /agents`. Reads power-profile YAML
  on register (validate against schema).
- **Depends on**: `registry.openapi.yaml`, `power-profile.schema.yaml`.
- **Done signal**: CRUD unit tests green; register→persist→reload survives a restart in a
  tmpdir; invalid power-profile rejected with a named error.

### Lane C — Agent image + server  (`agent/`, `tests/agent/`)
- **Build**: `POST /infer` (echo + a demo `toolCall` for MVP), `/healthz`. Containerfile
  **FROM `registry.access.redhat.com/ubi9/...`**; installs `openssh-server` +
  `openssh-clients`; `sshd` configured key-only (no passwords) for the CLI tab;
  entrypoint honors `--cpus/--memory/--pids-limit` and optional `--gpus all`.
- **Depends on**: `agent.openapi.yaml`, `protocol.schema.json`, `power-profile.schema.yaml`.
- **Done signal**: `podman build` succeeds; container starts, `/healthz` 200; `ssh` in
  with the test key lands at a `[bard@ubi9 ~]$` prompt; `ssh` *outbound* client present
  (`which ssh`).

### Lane D — Launch + ops scripts  (`scripts/`, `tests/scripts/`)
- **Build**: `run_agent.sh` (macOS/Linux), `run_agent.ps1` (Windows), self-signed
  cert-gen, model-fetch helper (curl/hf into the agent's model dir). Cross-platform
  primitives only (CLAUDE.md §4). Reads power-profile YAML to assemble podman flags.
- **Depends on**: `power-profile.schema.yaml`, the Containerfile's image name (string from
  Lane C's contract, not its code).
- **Done signal**: shellcheck/PSScriptAnalyzer clean; `run_agent.sh` dry-run prints the
  expected `podman run` line with limits + cert mounts for a sample profile.

### Lane E — CI + multi-arch build  (`ci/`, `.github/`)
- **Build**: GitHub Actions: lint + secret scan (gitleaks/detect-secrets per §6),
  per-lane unit tests on macOS + Linux, `podman buildx` multi-arch
  (`linux/amd64,linux/arm64`) push to a local registry. Unique build number per artifact
  (§11).
- **Depends on**: nothing in other lanes' *logic* — only their test entrypoints and the
  Containerfile path (interface: "each lane exposes `pytest tests/<lane>`").
- **Done signal**: workflow green on a branch with only Phase-0 + fakes present (lanes can
  fill in real tests later); manifest lists both arches.

### Lane F — Cross-platform client: CLI tab + Pro list UI  (`clients/app/`)
- **Hard requirements (from Eddie):**
  - **One codebase, five targets**: Windows, Android, macOS, Linux, iOS.
  - **Simple & professional GUI** — no decorative art, no skins; clean enterprise list +
    terminal. Matches features.md #39.
  - **Rock-solid, template-first** — start from the framework's *official* starter
    template and well-known component libraries; **do not hand-roll novel UI**. This
    project explicitly moves **off Swift/SwiftUI**, which produced recurring weird bugs in
    the consumer app (e.g. the `-Onone` SIL-inliner workaround, Swift #88173 — see
    `project_swift_inliner_bug` memory). The whole point is to avoid that class of issue
    by using a mature, single-language, cross-platform toolkit.
- **Framework**: **Flutter / Dart** (decided — §8g). All five targets from one codebase,
  official Material 3 professional widgets + `flutter create` template, no Swift-toolchain
  coupling. Start from the stock template; do not hand-roll novel UI.
- **Build**: thin client over the HTTP contracts: (1) **ssh-backed CLI tab** via
  **`dartssh2`** (key-based attach to the agent's `sshd`; **NEW DEP, flag license/ARM/
  maintenance before adding** per §13), and (2) the **professional model list**
  (name/provider/params/quant/size/status) using stock Material list components. No custom
  rendering, no platform-specific UI forks beyond what the template provides.
- **Depends on**: `protocol.schema.json`, `router.openapi.yaml` (non-ssh API path); §8(g)
  framework decision.
- **Done signal**: `<framework> create` template builds & runs on macOS + one of
  {Windows, Linux} + Android; model list renders from a `FakeRouter` JSON fixture; ssh
  package decision raised to Eddie (not merged unilaterally).

---

## 7. Dependency graph & phasing

```
Phase 0 (serial, 1 agent):  contracts/ + common/ + tests/fakes/   ──► freeze
                                              │
        ┌──────────────┬────────────┬────────┴───────┬───────────────┬──────────────┐
Phase 1 (parallel):  Lane A      Lane B          Lane C          Lane D          Lane F
                     Router      Registry        Agent+ssh       Scripts         iOS spec
        └──────────────┴────────────┴────────────────┴───────────────┘
                                              │
Phase 2 (integration, 1 agent):  wire real Router↔Registry↔Agent, replace fakes,
                                  end-to-end text request on a single LAN, README + ADRs.

Lane E (CI) starts at end of Phase 0 and runs alongside Phase 1 — it only needs the
test/build entrypoints to exist, not the logic.
```

Why this parallelizes cleanly:
- Lanes A/B/C never import each other — they talk over **HTTP contracts** and test
  against **fakes**. The only true serial gate is Phase 0 (freeze) and Phase 2 (join).
- Lane D depends on a *string* (image name) and a *schema*, not on Lane C's code.
- Lane F is mostly independent (different language, different eventual repo).
- Each lane has a self-contained done signal, so an agent verifies its own work without
  waiting on another lane.

Anti-collision rules (restate for agents): edit only your lane's dir; read contracts,
never patch them in-lane; if you need a contract change, stop and flag it; keep files
≤500 lines and commit per Conventional Commits with a version bump (CLAUDE.md §3, §11).

---

## 8. Open questions (resolve before/while building)

- **(a) Where does the UBI agent run** for the iOS CLI tab? iOS can't host it — remote
  Linux/desktop over Tailscale-IP, a Mac/Linux sidecar, or cloud. *Leaning: remote agent
  reachable over Tailscale-IP, reusing the consumer app's #16 terminal endpoint + #21
  Tailscale detection.* (features.md #38a.)
- **(d) Model downloads** land in the container volume vs sync back to the iOS model
  store? (features.md #38d.)
- **(e)** Does the Pro CLI tab deprecate the consumer simulated `vibe` CLI (#20) or ship
  as a separate "Pro" tab? (features.md #38e, #39.)
- **(g) Cross-platform GUI framework — DECIDED 2026-06-07: Flutter.** One Dart codebase →
  Windows + Android + macOS + Linux + iOS; official `flutter create` starter + Material 3
  professional widgets; no Swift/SwiftUI coupling. (Alternatives considered and rejected
  for MVP: Tauri 2 — mobile younger; Compose MP — iOS newest leg; .NET MAUI — no
  first-class Linux. Capture in `ADR-0005`.)
- **ssh client package**: **`dartssh2`** is the candidate — license/ARM/maintenance review
  required before adding (§13).
- **GUI design language**: simple, professional, enterprise. No album art, no skins, no
  phonograph/cassette motifs. Confirm a neutral palette + system fonts.
- **(h) Workgroup identity & trust fabric (features.md #42) — post-MVP, own phase.** Per-
  entity keypair; manager-administered workgroups; per-workgroup roles (a member of WG-A
  can manage WG-B); multi-membership entities bridge messages between their workgroups.
  This is a federated trust + capability layer that **supersedes the MVP's single-registry
  + JWT auth** and overlaps the deferred mesh. **Do not bake JWT-only assumptions deep into
  Lanes A/C** — keep `authToken` validation behind an interface so a PQ-identity verifier
  can replace/augment it later. PQ caveat: stock OpenSSH offers PQ *key exchange* but not PQ
  *identity/signature* keys; PQ identity means app-level **ML-DSA (FIPS 204)** signing via a
  lib like liboqs, not `ssh-keygen`. Decision: hybrid-now vs ML-DSA-identity-day-one (#42).
  **→ Full design drafted in `TRUST_MODEL.md`** (2026-06-07): zero-trust "tailnet per
  workgroup", hybrid PQ identity, MLS (RFC 9420) group keying re-keyed on membership
  change, two-gate device approval, total revocation, trust-translation bridging; optional
  self-hosted **Headscale** mesh + upstream-tracking pipeline (#43). Open sign-offs D1–D5.

## 9. Next steps for Claude

1. **Phase 0 (one agent, serial)**: scaffold `contracts/`, `common/config.py`,
   `tests/fakes/`. Get the schemas reviewed/frozen.
2. Write ADRs: `ADR-0001 Router/Agent JSON protocol`, `ADR-0002 No-mesh MVP`,
   `ADR-0003 UBI-9 + Podman agent`, `ADR-0004 ssh-backed CLI tab`,
   `ADR-0005 Flutter cross-platform client (off Swift/SwiftUI)`.
3. **Phase 1**: launch Lanes A–F in parallel (one agent per lane).
4. **Phase 2 (one agent)**: integration, end-to-end LAN test, regenerate README.
5. When code outgrows docs, split `bardLLMPro/` into its own GitHub repo.
