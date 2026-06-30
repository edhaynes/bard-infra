# JOURNAL — Refinery Self-Discovery Demo

Newest on top. Latest is greatest; a newer entry supersedes older ones on conflict.

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
