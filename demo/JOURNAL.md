# JOURNAL — Refinery Self-Discovery Demo

Newest on top. Latest is greatest; a newer entry supersedes older ones on conflict.

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
