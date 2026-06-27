Status: Not Implemented — proposed demo build plan (awaiting go). 2026-06-09.

# PLAN — "Stranded Compute → Open Inference Pool" demo (for Chris Wright, 15 min)

> Pivot of the MVP toward a **demoable** artifact for a 15-min Red Hat CTO meeting.
> Decisions locked (Eddie 2026-06-09): centerpiece = **pooled fleet + a live job**;
> fidelity = **all real, small fleet** (3–4 real UBI+Podman agents); dashboard =
> **reuse cdn-sim**. Tailored to Chris Wright (open / any-model-accelerator-cloud /
> SELinux / sustainability — see `docs/outreach/`). This reprioritizes the v1 sprints:
> S3's self-register + capability advertisement now feed the demo.

## The 15-minute story (what Chris sees)
1. **The stranded compute** — dashboard shows a fleet of heterogeneous UBI+Podman nodes
   (a GPU workstation, a dev laptop, a storage node, an ARM edge box), each advertising
   idle CPU/GPU/RAM/storage and a **SELinux-confined, rootless** badge. "Hardware you
   already own and power."
2. **The pool** — aggregate idle capacity across the fleet. Framing: **sustainability +
   democratization** — no new GPU spend.
3. **A real job lands** — submit an inference prompt; the control plane places it on a
   capable node (GPU-preferred, CPU-fallback = "any accelerator") and returns a **real
   completion from an open model (Red Hat Granite)**. The money shot.
4. **Why it's safe & open** — **rootless UBI + Podman**, open end-to-end (UBI, Podman,
   llama.cpp, open models, Valkey, OpenMLS), over the Tailscale/WireGuard mesh.
   **MVP runs permissive container perms** (Eddie 2026-06-09); the **fine-grained SELinux
   default-deny sandbox with cgroup limits (#48)** is the hardening *roadmap* — present it
   as the path (honest for an LSM maintainer), not as enforced today. Do **not** badge
   nodes "default-deny" in the MVP demo.
5. **Where it plugs into Red Hat** — OpenShift path; complements RHEL AI / InstructLab.

## Reuse vs build
- **Reuse (have):** UBI+Podman agent w/ real llama.cpp (verified), Registry (JSON store,
  capability schema `power-profile.schema.yaml`), Router, cdn-sim dashboard (React19+Vite,
  deck.gl). 100% Python coverage gate is live — new Python holds the line.
- **Build:** fleet of agents advertising capability, pool aggregation, capability-aware
  placement, the cdn-sim fleet/pool/job view, an open model, one-command bring-up + runbook.

## Phased build (small, verifiable steps — §17 plan sizing; each step: tests + 100% branch cov + green-before-commit + healthy-before-handover)

### Phase 0 — Demo definition (½ day)
- 0.1 Write the runbook: the 5-beat storyboard above + verbatim talking points + the fleet
  personas (4 nodes, their capability profiles). → `docs/demo/RUNBOOK.md`.

### Phase 1 — Fleet & capability (backend; this IS Sprint 3, retargeted)
- 1.1 **Agent self-registers on boot** — startup hook POSTs `/register` (config: registry
  URL + own advertised address). Tests for present/absent/failed registry. *(S3 item)*
- 1.2 **Agent advertises a capability profile** on register (per `power-profile.schema`):
  detect real CPU cores + RAM; GPU/storage/net from config/env to stage heterogeneity.
  Registry persists capability per agent; `GET /agents` returns it. Tests.
- 1.3 **Pool aggregation** — `GET /pool` on the Registry returns total + available
  CPU/GPU/RAM/storage across registered agents. Tests (empty, one, many, mixed).
- 1.4 **Capability-aware placement** — Router (or a `/schedule`) picks a node by workload
  need (LLM → GPU-preferred, CPU-fallback); returns chosen agentId. Tests for match/
  fallback/none-available.
- 1.5 **Fleet bring-up** — `scripts/demo_fleet.{sh,ps1}` starts Registry + Router + N
  agent containers (rootless Podman, distinct profiles, SELinux labels). `sh -n`/shellcheck.

### Phase 2 — Open model
- 2.1 Point `fetch_model` default at **Red Hat Granite** (open GGUF, small variant); verify
  a real completion through the container (healthy-before-handover). Keep Qwen as fallback.

### Phase 3 — Dashboard (cdn-sim reuse — the visual centerpiece)
- 3.1 Stand up cdn-sim as the demo dashboard (its chrome/panels) wired to the control plane
  (`/agents`, `/pool`, submit-job) via a typed API layer. *(deps already vetted; confirm.)*
- 3.2 **Fleet view** — nodes with capability + SELinux/rootless/default-deny badges + idle
  capacity (adapt `SubgraphCanvas`/`NocMap`).
- 3.3 **Pool view** — aggregate idle CPU/GPU/storage; sustainability framing.
- 3.4 **Live job** — "Run inference" → place on a node → highlight it → show the real
  Granite completion. The beat-3 money shot.
- 3.5 Polish — Red Hat-appropriate theme, narrative labels, latency display.

### Phase 4 — Dry run
- 4.1 Full rehearsal on the real fleet; latency sanity; **record a backup video** (live
  demos fail); finalize the runbook + a one-page leave-behind.

## Open decisions for Eddie
1. **Timeline** — when's the meeting (even rough)? Drives minimum-lovable scope: the
   irreducible demo is Phases 1+3.4 (fleet → pool → live job); Phases 2/3.5/4 are polish.
2. **Granite vs Qwen** — chase Red Hat Granite GGUF (on-brand, "default to open") or keep
   the proven Qwen-0.5B for reliability and swap later?
3. **Dashboard deps** — the cdn-sim stack (React19/Vite/deck.gl/maplibre) needs `npm
   install` sign-off (the demo reuses it; deck.gl/maplibre are MIT/BSD).
4. **Real GPU node?** — "any accelerator" is strongest with one real GPU box in the fleet.
   Is one available, or do we show CPU nodes + one staged GPU profile (and say so)?
5. **Branch** — build the demo on the MVP branch (`claude/laughing-bell-57o15u`) or a
   dedicated `demo/*` branch? (Recommend the MVP branch — Phase 1 IS Sprint 3.)
