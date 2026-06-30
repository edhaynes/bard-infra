Status: Implemented, 2026-06-30 — all 8 sprints done (console awaits Eddie's visual sign-off, §14)

# PLAN — Refinery Self-Discovery Demo (`demo/`)

Author: Jason-meta
Created: 2026-06-30
Repo: bard-infra (PUBLIC — synthetic/public data only; no customer/site/commercial material)

## 1. What this demo proves

A refinery is **stood up in seconds by self-discovery**: every field element (sensor,
valve, PLC, switch, gateway, workstation) **self-registers into the real bard-infra
Registry** the moment it powers on, and a **management console** renders the live plant.
From the console an operator runs the two critical operations — **bring-up** (ordered
startup) and **bring-down** (ordered shutdown) — and the demo **injects and handles
failures** (element drops offline, gas alarm trips the SIS, loss of steam cascades).

The bard-infra hook: a "refinery element" *is* a bard-infra agent. Self-registration +
heartbeat = real "plug it in and it appears." Heartbeat-going-stale = a real
element-offline failure signal, straight from the fabric — no faked fault layer for
node-down.

Topology is modeled on **ExxonMobil Baytown** (public data): 3 pipestills (588k bbl/d),
vacuum, heavy conversion (FCC 220k + 2 cokers + hydrocracker + SDA), reforming/alky/
hydrotreating + SRU, utilities backbone, tank farm/blending. Synthetic element names use
Baytown-flavored, industry-standard tags (`Pipestill 7`, `Powerformer CRU-310`,
`FCCU-840`, `PT-101`).

## 2. The five sections (Baytown-mapped)

| # | Section | Real units |
|---|---|---|
| S1 | Crude & Vacuum (front-end separation) | 3 Atmospheric Pipestills (588k), Vacuum (297k), desalters, heaters |
| S2 | Conversion (cracking & coking) | FCC (220k), Hydrocracker (30.6k), Delayed Coker (54k), Fluid Coker (42k), SDA (47k) |
| S3 | Treating & Reforming | Powerformer (126.5k), Alky (44.5k), hydrotreater fleet, SRU, amine/SWS |
| S4 | Utilities & Offsites | H₂ plants, HP/MP/LP steam, cooling water, instrument air, power, **flare & relief**, fuel gas, DM water |
| S5 | Tank Farm, Blending & Shipping | crude/product tankage, gasoline/diesel/jet blending, coke handling, dock/pipeline/rail |

Each section is a Purdue cell: field sensors (temp/pressure/flow/level/gas) → control
valves/MOVs → PLC/DCS controllers **+ a parallel SIS chain** → industrial switch →
gateway → HMI/engineering workstation. Telemetry uses real ranges (FCC reactor
500–730 °C, hydrotreater 30–80 bar, PLC scan 1–20 ms, pump vibration trip ~7.1 mm/s).

## 3. Bring-up / bring-down ordering (hard interlocks)

**Bring-up (bottom-up):** S4 Utilities first (service water → firewater → instrument air →
DM water → HP/MP/LP steam → cooling water → fuel gas → **flare live** → H₂ plant) → S1
Crude & Vacuum → S3 enabling treating + SRU live → S2 Conversion → S3 reforming/alky + S5
blending/shipping.

**Interlock gates (hard, modeled):**
- Flare + relief in service **before any unit accepts hydrocarbons**.
- Steam + cooling water + BFW available **before any fired heater / column**.
- H₂ + recycle gas circulating **before feed to any hydrotreater/hydrocracker** (else
  reduced-temp hold to avoid coking the catalyst).
- SRU + amine/SWS live **before high-sulfur feed**.
- Crude/vacuum running **before conversion** (FCC/coker/HCU are fed by them).

**Bring-down (reverse / top-down):** conversion & octane first → crude/vacuum → treating/
SRU → utilities **last** (flare/steam/cooling water needed for safe depressurization).
Loss-of-steam / loss-of-feed process interlocks trip dependents (the cascade).

## 4. Architecture (3 tiers)

```
┌─────────────────────────────────────────────────────────────────┐
│ CONSOLE (React/Vite, cdn-sim chrome re-themed)                    │
│   reads Registry /agents,/pool,/fleet  (discovery + liveness)     │
│   reads Orchestrator /sections + SSE   (process telemetry + ctrl) │
│   renders 5-section schematic; bring-up/down/inject controls      │
└───────────────┬───────────────────────────┬─────────────────────┘
                │ (real bard-infra)          │ (new, demo/)
        ┌───────▼────────┐          ┌────────▼──────────────────────┐
        │ bard-infra      │          │ REFINERY ORCHESTRATOR          │
        │ REGISTRY (real) │◄─────────│  owns the process model:       │
        │ /register       │ projects │  - telemetry tick              │
        │ /agents /pool   │ every    │  - bring-up/down sequencer     │
        │ /fleet          │ element  │  - fault inject + propagation  │
        │ active|stale TTL│ as agent │  - element state machine       │
        └─────────────────┘          │  control API + SSE doorbell    │
                                      └────────────────────────────────┘
```

- **Tier 1 — bard-infra Registry (real, unchanged):** discovery + liveness fabric. The
  orchestrator projects every element into it via `POST /register` (agentId =
  `<type>.<section>.<tag>`, capabilities = `["type:sensor","section:S1","tag:PT-101"]`),
  heartbeating on a timer. Killing an element's heartbeat → real `stale` in `/agents` =
  element offline. **Zero Registry code change** — refinery semantics ride in the free-form
  `agentId` + `capabilities` (the `RegistrationBody`/`PowerProfile` schemas `forbid` extra
  fields, so we do NOT invent new fields).
- **Tier 2 — Refinery Orchestrator (new, in `demo/refinery/`):** the cdn-sim-derived sim.
  Owns everything the Registry can't carry — live telemetry values, element modes
  (offline/discovered/starting/running/tripped/down), bring-up/down sequencing with
  interlocks, fault injection + cascade propagation. Continuously projects elements into
  the Registry (Tier 1) and exposes a thin control API for the console.
- **Tier 3 — Console (new, in `demo/console/`):** clone of `clients/demo-console` (already
  reads bard-infra Registry + reuses cdn-sim chrome) + cdn-sim's `frontend/` widgets,
  re-themed. Joins Registry-discovered elements (identity+liveness) with orchestrator
  telemetry (live numbers) by agentId.

**Decision surfaced to Eddie (§4.1):** how much element STATE rides through the real
Registry. Two options — see the chat question.

## 5. Reuse map

| Source | Reused for |
|---|---|
| cdn-sim `cdn_graph/` (NetworkX graph, `compute_signals`, fault propagation, SSE doorbell, inject/resolve) | Orchestrator sim engine (adapt to refinery domain) |
| cdn-sim `frontend/` (grid chrome, KPI/Bottom/Ticker, api.ts SSE→REST transport, noc-theme CSS vars) | Console chrome + transport |
| bard-infra `clients/demo-console/` (reads Registry /agents,/pool; cdn-sim theme; seed fallback) | Console starting point (already Registry-wired) |
| bard-infra `scripts/demo_fleet.py` / `local_fleet_http.py` (FLEET list → POST /register + 15s heartbeat) | Registry projector template |
| bard-infra `agent/register.py` (`build_registration`, `mint_agent_token`, heartbeat_loop) | Projector contract (shared JWT, HS256, /register) |
| bard-infra Cloud Run (`router/Containerfile.cloud`, `scripts/deploy_loknet_router.sh`, `docs/demo/LOKNET_CLOUDRUN.md`) | Cloud Run deploy path (Secret Manager JWT, single-instance) |

## 6. Build sprints (each sized for ~90% first-go; contract-first per §11)

1. **Domain spec** — `refinery/topology/baytown.yaml`: 5 sections, units, elements
   (type/tag/telemetry-range/setpoint), network gear, SIS, edges (process flow + Purdue +
   shared dependencies for cascade), bring-up/down order + interlock gates. **Frozen contract.**
2. **Orchestrator core** — load topology → element objects; telemetry tick (PV near
   setpoint + noise); per-element state machine; section/plant signals (`compute_signals`
   analog). 100% branch cov.
3. **Registry projector** — register every element into a **real local bard-infra Registry**
   as an agent; heartbeat loop; verify live against the running Registry. Tests + live check.
4. **Sequencer + faults** — bring-up/bring-down with interlock gates; fault inject +
   propagation (loss of steam trips dependents; switch down → section blind; gas %LEL →
   SIS trip; pump vibration → Zone C; element-offline via stopped heartbeat). 100% branch cov.
5. **Control API** — FastAPI `/sections`, `/state`, `/bringup`, `/bringdown`, `/inject`,
   `/resolve`, `/reset`, `/events` (SSE), `/healthz`, `/version`. Contract-first, tested.
6. **Console** — clone demo-console; refinery theme; 5-section schematic (section cards →
   element detail); telemetry overlay (Registry identity/liveness + orchestrator values);
   bring-up/down/inject controls; alarm list; discovery feed. Playwright structural tests.
   **Visual verify with Eddie (screenshot) before "done."**
7. **Local run** — `scripts/run_local.sh`: Registry + orchestrator + console up & healthy
   (Tailscale/local pattern from `demo_serve.py`). End-to-end verified.
8. **Cloud Run (demo-ready)** — Containerfile + `deploy/deploy_cloudrun.sh`: single-instance
   Router-fronted Registry + co-located orchestrator + static console; JWT via Secret
   Manager (`--set-secrets`), never baked. Secret scan before any push/deploy.

## 7. Ports

Demo range `7090–7099` (avoids bard-infra 8081/8443/8444 and cdn-sim 7070/8080):
- Orchestrator API `7090`; Console (Vite dev) `5175`; local Registry `8081` (bard-infra default).
- Cloud Run: `$PORT`/8080 per bard-infra cloud convention.

## 8. Quality / constraints

- **API/contract first → tests → 100% line+branch coverage** on the Python (`--cov-branch
  --cov-fail-under=100`). Playwright for console structure; visual verify with Eddie.
- **Public repo:** synthetic/public data only; no customer/site/commercial material
  (§0.18). Secrets only via Secret Manager / gitignored `.env`; `.env.example` templated.
- **Rubric** in `demo/RUBRIC.md`; 90% working bar, 95% to publish.
- `README.md`, `JOURNAL.md`, `bugs.md`, `features.md`, `PLANS.md` under `demo/` (or folded
  into bard-infra root trackers — decide at scaffold).

## 9. Decisions (resolved 2026-06-30, Eddie)

1. **State-through-Registry split** — RESOLVED: **Registry carries discovery + liveness +
   classification ONLY** (identity, type/section/tag, active/stale = online/offline). Live
   telemetry values + control live in the Orchestrator and are overlaid in the console,
   joined by agentId. Self-discovery and element-offline are 100% real fabric; process
   numbers are the sim overlay. No telemetry encoded into capability tags.
2. **Cloud Run** — RESOLVED: **build local first** (Sprints 1–7 = working local/Tailscale
   demo), **Cloud Run is Sprint 8** (follow-on in the same pass, not a gate on the local demo).
3. **Trackers** — `demo/`-local (`demo/README.md`, `JOURNAL.md`, `bugs.md`, `features.md`,
   `PLANS.md`, `RUBRIC.md`); keeps the demo self-contained.
