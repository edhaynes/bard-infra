Status: Active — crawl/walk/run roadmap. v1 Crawl MVP complete 2026-06-10 (bardpro-v1.0.0); v2 Walk in progress — LokNet outbound-agent broker (feature #59, ADR-0013) complete: transport (v1.1.0), single front door (v1.2.0), real-socket mesh-free smoke (v1.2.1), Cloud Run deploy recipe authored (v1.3.0; public deploy is Eddie's, demo stays on Tailscale). **ADR-0014: two deployment profiles — Profile A (home hobbyist, ad-hoc, no console, zero mandatory cloud) is the FIRST PRODUCT MVP; Profile B (enterprise: management console, strict onboarding, MITM authorization) follows. The product is the backend API; Maude is the example client.**

# Bard — Roadmap & MVP Sprint Plan

> The single source of scope truth. `DESIGN.md` is the MVP architecture tiebreaker;
> this doc sits above it and defines **what lands in which release (crawl/walk/run)**
> and **the sprints to the first MVP**. The trust-layer docs (`TRUST_MODEL.md`,
> ADR-0006…0010) are **direction for v2/v3, not MVP** — see the tier table.

---

## Locked MVP decisions (Eddie, 2026-06-09)

| # | Fork | Decision |
|---|------|----------|
| 1 | Inference path | **llama.cpp inside the UBI agent** (LiteLLM routes to its OpenAI-compatible server). Replaces the `EchoEngine` stub. |
| 2 | ssh CLI tab | **Out of MVP** → v2 (Walk). |
| 3 | Remote agent spawn/lifecycle | **Out of MVP** → v2 (Walk). MVP routes to an already-running agent. |
| 4 | Registry persistence | **JSON-file** behind the existing `store.py` interface. Valkey lands with the control plane in v2. |

Settled earlier and unchanged: no mesh (direct TLS over LAN), text-only (`voice → 501`),
NVIDIA-on-Linux HW accel only, JWT auth behind a swappable verifier interface (the seam
a PQ verifier replaces later). **Client (re-decided 2026-06-10, ADR-0011): the Maude iOS
app (claudeTalk repo) is the v1 client** — Flutter moved to v2 for Windows/Linux/Android
breadth; no console in MVP.

**Client platform priority:** v1 ships on iOS/macOS via **Maude** (ADR-0011, 2026-06-10 —
supersedes ADR-0005 for MVP scope; claudeTalk v0.1.0 already speaks JWT + `POST /v1/message`
against the live contract). The 2026-06-09 cross-platform-by-construction requirement moves
with Flutter to **v2**: single Flutter codebase, no platform UI forks, Windows/Linux/Android
validated after mac/iOS. The `clients/app/` skeleton stays, marked v2.

---

## Crawl / walk / run

| | Theme | Contents |
|---|---|---|
| **v1 — Crawl** *(MVP, Sprints 0–4)* | One LAN, real model, pragmatic auth | Maude client (ADR-0011) → Router → Registry(JSON) → UBI agent w/ **llama.cpp**, TLS + JWT, NVIDIA-on-Linux. **No** mesh / voice / console / remote-spawn / ssh-tab / trust-fabric. |
| **v2 — Walk** | Multi-host Pro usability; still pragmatic crypto | ssh CLI tab (Sprint 5) · remote compute spawn/lifecycle (Sprint 6) · **Valkey source-of-truth + control-plane single front door** (replaces JSON file; ADR-0010) · **React management console** for org scale (ADR-0007/0008) · OO domain model (workgroups/devices/permissions) with **software identity keys + JWT-class auth** · pragmatic encryption-at-rest (AES-256, OS-managed keys) · mesh as an **opt-in** pluggable transport (Tailscale/Headscale). |
| **v3 — Run** | Full zero-trust fabric + enterprise hardening | Hybrid-PQ identity (Ed25519+ML-DSA-65), **hardware-backed where available — TPM optional** (ADR-0006/0009) · MLS group keying (OpenMLS) + per-epoch re-key + revocation · cross-workgroup bridging · HPKE PQ envelopes, PQ-everywhere, encryption-at-rest with non-co-located KEKs · hidden objects / blinded-handle discovery · HA Valkey cluster + federated managers + two-gate approval w/ attestation. |

**Discipline:** v2 introduces the *shapes* (domain model, control plane, encryption-at-rest,
mesh) behind **boring, swappable crypto**; v3 swaps the verifier / keystore / group-engine
**without re-architecting**. Every irreversible "Accepted" earns its stamp only after code
in the relevant tier votes.

### ADR / doc → tier map

| Doc | Tier | Notes |
|---|---|---|
| ADR-0001 wire protocol · ADR-0002 no-mesh · ADR-0003 UBI+llama.cpp agent · ADR-0011 Maude v1 client | **v1 — Crawl** | Accepted; code exists or lands in Sprints 1–4. |
| ADR-0005 Flutter client | **v2 — Walk** | Superseded for v1 by ADR-0011 (2026-06-10); rationale stands for v2 Windows/Linux/Android breadth. |
| ADR-0004 ssh CLI tab | **v2 — Walk** | Direction accepted; scheduled Sprint 5. |
| ADR-0007 React console · ADR-0008 client/console split · ADR-0010 OO GUIs + Valkey | **v2 — Walk** | Proposed; not built in MVP. (PQ-at-rest parts of 0010 are v3.) |
| ADR-0006 zero-trust PQ identity · ADR-0009 three-tier identity keys · `TRUST_MODEL.md` | **v3 — Run** | Proposed direction only; not committed/built. "D1–D5 accepted" = accepted *direction for v3*, not an MVP commitment. |

---

## TPM is optional → tiered device assurance (v3 trust layer)

Hardware-backed, non-exportable identity keys are **preferred, not mandatory**. The trust
layer is a **two-tier assurance** model, not a hardware binary:

- **High assurance** — hardware-backed key + (optional) attestation present: Secure Enclave,
  Android StrongBox, or a TPM 2.0 that happens to be available. Eligible for privileged
  roles / sensitive workgroups.
- **Standard assurance** — **software-protected key** (OS keystore / encrypted-at-rest
  software key) when no TPM/enclave. The device still joins; the manager sees a lower
  assurance level and can policy-gate what it may do.

Implications folded into the (deferred) trust docs: attestation becomes **optional** at
device-approval gate 1 with the assurance level recorded on the member leaf; ADR-0009's
"revoking the device is final" holds only for **non-exportable hardware keys** — software
keys also need a key-rotation path.

---

## Sprints to MVP

~1-week sprints, agent-driven. Sprint 0 is a half-sprint. Sprints 1 and 2 sit behind frozen
contracts/fakes, so they **parallelize** (≈4 weeks calendar with two agents).

### Sprint 0 — Reconcile & freeze (½ wk) — *this commit*
- Apply A1–A6 corrections to `BARD_LLM_PRO_ARCHITECTURE.md` + `_MVP_SPEC.md` (strike
  iSH-runs-container, dedup the high-water-mark paragraph, "LiteLLM-is-the-router", no
  mesh / text-only / NVIDIA-only).
- Write **ADR-0001…0005** from settled decisions.
- Demote `TRUST_MODEL.md` + ADR-0006…0010 to *Proposed / deferred* with roadmap tiers.
- Capture TPM-optional tiering + crawl/walk/run (this doc, `docs/MEMORY.md`, `PLANS.md`).
- **Done:** no doc asserts iSH/mesh/voice/two-GUI/remote-spawn in MVP; ADR set 0001–0010
  complete with correct statuses + tiers.

### Sprint 1 — Real inference (llama.cpp) — ✅ code-complete (v0.1.3; build/live-run CI-deferred)
> 1a engine + selector + tests · 1b multi-stage Containerfile · 1c model-fetch +
> entrypoint · integration reconcile + e2e test. 36 tests green, ruff clean, echo
> smoke PASS. The multi-arch `podman buildx` build and a live model run move to CI
> (Lane E / Sprint 4) — no podman/llama.cpp binary in the dev sandbox.
- `LlamaCppEngine` implementing the `InferenceEngine` protocol → LiteLLM → llama.cpp
  OpenAI-compatible server.
- Containerfile builds/installs llama.cpp on `linux/amd64` + `linux/arm64`; config-driven
  model-fetch (small GGUF); optional `--gpus all` + NVIDIA libs.
- Split for AI-execution safety (CLAUDE.md §17): **1a** engine + LiteLLM wiring against a
  locally-run llama server · **1b** multi-arch Containerfile · **1c** model-fetch + entrypoint.
- **Done:** `podman run` agent → `/infer` returns a real completion; `/healthz` 200; unit
  test with a tiny or mocked model.

### Sprint 2 — ~~Flutter client wired to the router~~ (REMOVED from MVP, 2026-06-10 — ADR-0011: Maude is the v1 client; this sprint's content moves to v2 with Flutter)
- Settings (router URL + token via config layer); model list from `GET /agents`; compose →
  `POST /v1/message` → render; error-envelope handling; Dart domain model generated from
  the contracts (thin widgets per ADR-0010).
- **Done:** client on **macOS + iOS** (the priority targets) sends a prompt to a live router
  and shows a real llama.cpp answer; keep Windows/Linux/Android **building** (no mac/iOS-only
  API without a fallback); `flutter analyze` clean, widget tests green.

### Sprint 3 — End-to-end on one LAN (DESIGN Phase 2)
- Real Router↔Registry↔Agent wiring; agent self-registers on boot; real TLS certs
  end-to-end; JWT from a minimal auth stub (verifier stays behind the interface — the PQ
  seam); power-profile YAML limits applied at launch; `/version` (vX.Y.Z + sha + date) on
  router + agent, shown in client.
- **Done:** `scripts/smoke_local.py` brings up the stack; client gets a real answer;
  latency sanity (NFR-2); secret scan + lint green.

### Sprint 4 — Package, CI multi-arch, docs, release
- CI: lint + secret scan, tests on macOS + Linux, `podman buildx` multi-arch image w/
  llama.cpp, unique build number (§11); finalize `run_agent.sh/.ps1` + one-command
  bring-up (NFR-4); **regenerate README from scratch** (§8); tag + CHANGELOG.
- **Done:** green CI on a clean clone; a fresh machine follows the README → working LAN
  MVP; multi-arch manifest lists both arches.

**→ 5 sprints (0–4) to a shippable MVP.**

### Post-MVP (v2 — Walk)
- **Sprint 5 — ssh CLI tab:** key-only `sshd` + `openssh-clients` in the UBI agent;
  `dartssh2` terminal tab in Flutter (**flag license/ARM/maintenance per CLAUDE.md §13
  before merging the dep**).
- **Sprint 6 — Remote compute lifecycle:** explicit remote host + spawn/teardown via Podman
  remote API / agent spawn endpoint; remote model dir.
- Then: Valkey + control plane (migrate off JSON store), React console, OO domain model with
  software-key trust.
