# JOURNAL — Refinery Self-Discovery Demo

Newest on top. Latest is greatest; a newer entry supersedes older ones on conflict.

## 2026-06-30 — Self-heal (autorepair) + cascade-walk DONE — the "whole point"

- **Self-heal agent** (refinery/selfheal.py) — deterministic detect→diagnose→remediate,
  no LLM. AUTO-heals safe/reversible faults (reroute/failover/twin-promote) after a short
  delay; HOLDS dangerous SIS/gas trips for human Approve/Reject. /agent/* endpoints +
  /state summary. Console SelfHealPanel (on/off, AUTO/APPROVE, live events w/ approve/
  reject). The pitch: cdn-sim proposes-and-waits; ours self-heals (human gate for danger).
- **Cascade-walk** — faults._cascade records BFS propagation order; InvestigateView pulses
  the affected devices red one step at a time (the trip propagating), clearing on heal.
- 119 py tests 100%; 6 Playwright tests. Screenshots: console-selfheal.png,
  console-cascade-walk.png.
- **Remaining threads:** Fabric tab (wire fabric.py twin/failover to UI + real Valkey) ·
  bard-infra boxes/public-keys/OO tab · ISA-101 HMI restyle (alarm banner, PV/SP/OP
  faceplates, multi-pen trends, sparklines, grey canvas).

## 2026-06-30 — Console v2: Investigate tab + realism timeline DONE (threads 1 + realism)

- **Thread 1 (Investigate)** shipped — radial OT-network circle diagram of all 116 devices.
- **Realism** shipped (Eddie: "you don't bring down a refinery in 5s, it'd explode"):
  STOPPING controlled-cooldown state (symmetric to STARTING ramp), bring-up AND bring-down
  now ~89 ticks (≥60s, no cliff), plant-time compression (1 tick = 12 plant-min, so a
  bring-up reads ~14h), off-kilter `flagged[]` in /state, and a **bottom simulation
  timeline** (mode + plant clock + 5 section stage-bars + units + off-kilter flag).
  105 py tests 100%; 5 Playwright tests. Screenshots: console-investigate.png,
  console-timeline-bringdown.png.
- **Distributed fabric foundation** committed (refinery/fabric.py): replicated AreaStore
  (in-memory + Valkey behind interface) + failover + digital twin. Not yet wired to the
  orchestrator/console.
- **Linda's feature-retention verdict** (drives the rest): final tabs = Overview ·
  Investigate (+ cascade animation + self-heal overlay) · Fabric. Drop Topology/Runbooks/
  LLM-key UI. Headline: cdn-sim *proposes-and-waits*; refinery **self-heals** (closed,
  deterministic loop; human gate for dangerous actions).
- **Next threads:** self-heal (autorepair, "the whole point") + node-walk cascade
  animation · Fabric tab (twin/failover) · bard-infra boxes/keys tab · ISA-101 restyle.

## 2026-06-30 — Console v2 underway (Eddie, live iteration); Cloud Run LIVE

- **Deployed to Cloud Run** (potent-catwalk-415015 / Bard Technical Solutions):
  https://refinery-demo-877819400319.us-central1.run.app — dashboard + API live.
  (Cloud Build API just-enabled propagation caused a first-try 403; retry succeeded.)
  Known: deployed image predates the v2 endpoints; `/healthz` 404 quirk to re-verify on
  the v2 redeploy. Deploy fixes committed (.gcloudignore, script --tag/--config).
- **Eddie's console-v2 direction** (rapid live iteration → DESIGN_industrial_fabric.md,
  features #10-18). The Investigate tab grows into the bard-infra industrial pitch:
  legacy PLC/SCADA vs distributed fabric (microcontroller-per-device + self-discovery +
  ARM gateways + **Valkey** replicated areas + digital twin + failover). New bard-infra
  tab (boxes + public keys + OO comms). ISA-101 HMI restyle (Linda's sourced style guide:
  grey canvas, alarm banner, PV/SP/OP faceplates, multi-pen trends/sparklines).
- **Thread 1 DONE + shown:** Investigate tab — radial OT-network "circle diagram" of all
  116 devices (PLANT core → section spokes → Purdue rings; type-coloured, trouble-lit).
  Backend /netgraph + /graph + /history. 95 py tests 100%; 4 Playwright tests.
  Screenshot docs/screenshots/console-investigate.png.
- **Threads queued (one at a time):** 2 distributed-fabric sim (Valkey areas/twin/
  failover + A/B toggle) · 3 bard-infra boxes/keys tab · 4 ISA-101 HMI restyle.

## 2026-06-30 — Sprint 8 done: Cloud Run demo-ready (image built + run-verified)

- `refinery/api.py` — orchestrator optionally serves the built console same-origin
  (`REFINERY_CONSOLE_DIST`), so ONE service hosts API + dashboard. 92 tests, 100% branch.
- `deploy/Containerfile` — UBI multi-stage (ubi9/nodejs-20 builds the console with
  `VITE_ORCH_BASE=""`, ubi9/python-312 runs the orchestrator on `$PORT`).
  `deploy/deploy_cloudrun.sh` (single-instance, no secret for the visual demo) +
  `deploy/DEPLOY.md` (layer A visual demo; layer B real-Registry self-discovery via
  on-prem/Tailscale or LokNet, Secret-Manager JWT).
- **Built + run-verified with podman**: image builds clean; container serves dashboard at
  `/`, `/state` (116 elements, tick advancing), bring-up via API — all on :8080.
- Actual `gcloud run deploy` is Eddie's to fire (needs his gcloud auth).

### ALL 8 SPRINTS DONE — demo is feature-complete.
Backend 100% branch-covered (92 tests); self-discovery proven on the real Registry;
console built (awaiting Eddie's visual sign-off, §14); one-command local run; container
builds + runs. Remaining for Eddie: visual sign-off on the console + fire the Cloud Run
deploy. Follow-ups parked in features.md (#8 per-device identity, #9 live-Registry
discovery panel).

## 2026-06-30 — Sprint 7 done: one-command local run (full real stack)

- `scripts/run_local.py` — cross-platform launcher (subprocess + pathlib, no shell):
  starts the real bard-infra Registry, the orchestrator, the fleet projector, and the
  console, wired with an ephemeral in-memory JWT secret (never persisted), waiting on
  each `/healthz`. `--no-console` for backend-only.
- Verified live: Registry healthy → orchestrator healthy → projector registered all
  **116 elements** into the real Registry → orchestrator serving 116 elements. The whole
  demo (incl. real self-discovery) comes up with one command.

## 2026-06-30 — Sprint 6 built: management console (cdn-sim chrome, re-themed)

- `console/` — React 19 + Vite + TS. cdn-sim NOC Spectrum-blue theme re-themed to a
  5-section card grid: top bar (bring-up/down/reset + mode/blocked pills + tick),
  KPI strip, 5 section cards (units + live telemetry + status dots + network gear),
  side panel (inject fault with live target list + incident list w/ Resolve).
- Single-origin: console talks only to the orchestrator (CORS). Discovery story told
  via element states; live-Registry discovery panel is a follow-up (features #9).
- Builds clean (vite, 35 modules). 3 Playwright structural tests pass against the live
  stack (5 sections render, bring-up via UI, fault opens incident).
- **Screenshots captured** (`docs/screenshots/`): running plant (19/19 green) +
  gas-release cascade (FCC trips, S2/S3/S5 red, incident "4 downstream tripped"). Eddie
  out today → **awaiting his visual sign-off before this is "done" (§14).**
- Eddie's approved direction: cdn-sim chrome + 5-section cards.

## 2026-06-30 — Sprint 5 done: control API (FastAPI)

- `refinery/api.py` — `Orchestrator` (owns sim+seq+faults) + `create_app`: GET
  /healthz /version /state /sections /elements /faults; POST /bringup /bringdown
  /inject /resolve/{seq} /reset /step. CORS for the console dev origin. 90 tests,
  **100% line+branch**.
- `refinery/server.py` (coverage-excluded) — uvicorn entrypoint + background tick loop
  (REFINERY_TICK_SECONDS). Verified healthy live: ticker advances, bring-up over HTTP
  drove to 19/19 units, /sections returns all 5.
- **Deviation from plan:** orchestrator uses `/state` POLLING, not SSE — at a 1s tick
  it's equivalent to cdn-sim's SSE-doorbell, fully testable, no untestable infinite
  stream. Console polls /state + /sections + Registry /agents. (Eddie out today; low-risk
  call, easy to add SSE later if wanted.)
- Note: server.py uses `@app.on_event` (deprecated in newer FastAPI but functional on
  0.136); switch to lifespan if it ever warns louder.

## 2026-06-30 — Sprint 4 done: bring-up / bring-down sequencer + fault cascade

- `refinery/sequencer.py` — dependency-correct order (topo sort over feeds+utility+
  interlock-gate edges); cascading tick-driven bring-up; leaf-first gradual bring-down
  (snapshot-before-mutate); utilities/network last. Caught + fixed a one-tick bring-down
  collapse via the status snapshot.
- `refinery/faults.py` — inject `unit_trip`/`loss_of_utility`/`gas_release`/`switch_down`/
  `pump_vibration`/`element_offline`; cascade trips running downstream dependents through
  the shared dependency graph; resolve restores. `element_offline` mirrors the real
  Registry-stale signal.
- Extracted `dependency_graph(ref)` shared by sequencer + faults.
- Backend behavior model now complete. **77 tests, 100% line+branch** across all modules.

## 2026-06-30 — Sprint 3 done: self-discovery into the REAL Registry (verified live)

- `refinery/registry_projector.py` — mints one shared fleet JWT (HS256, bard-infra
  contract) and `POST /register`s every element as a bard-infra agent
  (`agentId=<type>.<section>.<tag>`, refinery semantics in `capabilities` tags, no
  Registry code change); heartbeat loop re-registers each interval (re-register IS the
  heartbeat). Fail-fast on missing/short secret. `scripts/project_fleet.py` drives it.
- 55 tests, **100% line+branch** (Registry mocked with respx; no network in unit tests).
- **Live-verified against the real bard-infra Registry** (`uvicorn registry.main:app`,
  TTL=3s): 116 elements registered → all `active`; stop heartbeat → all 116 `stale`
  after TTL (the real offline signal); re-register → all `active`. Self-discovery +
  liveness are real fabric, not simulated.

## 2026-06-30 — Sprint 2 done: orchestrator core (runtime + telemetry)

- `refinery/sim.py` — `ElementRuntime` state machine (offline/discovered/starting/
  running/tripped/down) + deterministic seeded telemetry tick (ramp on startup, jitter
  near setpoint, safe-state on trip, zero when idle); `RefinerySim` holds all element
  runtimes, ticks them, sets unit/section/element state, and computes plant + per-section
  signals (worst-wins rollup, alarm/trip detection gated to live states).
- 44 tests total, **100% line+branch** across model + sim.
- Sequencing + fault injection deferred to Sprint 4 (this is the substrate they drive).

## 2026-06-30 — Sprint 1 done: frozen topology contract

- Scaffolded `demo/` as a standalone uv project (orchestrator package `refinery/`),
  isolated from bard-infra's core 100% coverage gate.
- `refinery/topology/baytown.yaml` — Baytown-modeled (public data) 5-section refinery:
  S4 Utilities → S1 Crude & Vacuum → S3 Treating & Reforming → S2 Conversion → S5 Tank
  Farm & Blending. ~110 synthetic elements with real telemetry ranges; bring-up interlock
  gates (flare/steam/cooling/H₂/SRU/crude) and process+utility dependency edges.
- `refinery/model.py` — loader + dataclasses + networkx dependency graph (FEEDS process
  edges + CONSUMES utility edges) + validation. **22 tests, 100% line+branch coverage.**
- Decisions (Eddie, this session): real bard-infra Registry (not simulated); Registry
  carries **discovery + liveness only**, telemetry/control in the orchestrator overlaid in
  the console; **local first, Cloud Run is Sprint 8**.
- Fixed during build: VPS-1 fed two undefined units (U-730/U-470) — repointed to U-720/U-610.

## 2026-06-30 — Demo conceived

- Eddie: last QNX-demo focus is bard-infra. New `demo/` shows a refinery quickly hooked up
  via self-discovery, with a cdn-sim-based management console re-themed to a refinery.
- Pillars: self-discovery · 5 sections · bring-up · bring-down · failure handling.
- Reuse cdn-sim heavily (graph sim backend + React console chrome); model topology after a
  real Exxon refinery (Baytown). Plan: `PLAN_refinery_demo.md`.
- Parked: Maestro mispronouncing again — Eddie will likely narrate the demo video himself;
  no Maestro TTS wired into this build. (shared-rules §14.2 lexicon should prevent this.)
