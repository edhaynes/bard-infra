Status: Implemented, 2026-06-30 (local-real + Fleet tab; Cloud Run stays sim per Eddie)

# PLAN — Make bard-infra real + the Fleet node-browser dashboard

Author: Jason-meta
Two coupled goals: (A) stop faking — wire the console to the **real bard-infra Registry**;
(B) a **node-browser dashboard** to browse all nodes in a collapsing tree, surfacing failed
nodes and network-connectivity problems. They share the same data path, so build together.

## A. Make bard-infra real (console ← live Registry)

Today the console reads only the orchestrator sim. Fix:

- **Orchestrator gets a Registry client.** Config: `REFINERY_REGISTRY_URL`, `REFINERY_JWT_SECRET`,
  `REFINERY_JWT_ISSUER` (reuse the projector's HS256 token mint). Fail-soft: if unset/unreachable,
  endpoints report `{"registry": "disconnected"}` (no crash — the sim still works).
- **`GET /discovery`** (server-side): mint a fleet token, `GET {Registry}/agents`, return the live
  agent list `[{agentId, status: active|stale, capabilities, lastSeen}]`. The browser never holds a
  token. This is the **real self-discovery feed**.
- The 116 sim elements and the Registry agents are the same fleet (projector registers
  `agentId = <type>.<section>.<tag>`), so the orchestrator can **join sim element ↔ Registry agent**
  by agentId.
- Running it: `run_local.py` already starts the real Registry + projector; just point the
  orchestrator at `REFINERY_REGISTRY_URL`. (Cloud Run: see §C.)

## B. Fleet node-browser dashboard (new "Fleet" tab)

**Backend `GET /fleet`** — one record per node, joining sim + Registry + connectivity:
```
{ tag, type, section, unit, sim_state,            # running/tripped/down/starting/...
  registry: active|stale|absent,                  # real Registry liveness (heartbeat)
  reachable: bool, problem: str|null }             # network connectivity
```
- **reachable = false** when the node's path to the plant is broken: its **section switch is down**,
  its **section gateway is down**, or its **Registry agent is stale** (heartbeat lost). `problem`
  carries the reason ("section switch SW-S2 down" / "gateway GW-S2 down" / "heartbeat lost").

**Frontend — collapsing tree** (pulldown per level):
```
▾ PLANT                                    116 nodes · 4 failed · 3 unreachable
  ▾ S2 Conversion           ⚠              21 nodes · 4 failed · 3 unreachable
    ▸ network (SW-S2 ✕ down, GW-S2, HMI, EWS)
    ▾ U-840 FCC              ● tripped
        TT-8401  ● tripped   ✓active   ⚠ unreachable: SW-S2 down
        FV-8404  ● tripped   ○stale    ⚠ heartbeat lost
    ▸ U-610 Hydrocracker     ● running
  ▸ S1 Crude & Vacuum                       29 nodes · 0 failed
```
- Each node row: sim-state dot · **Registry badge** (●active / ○stale) · **connectivity** (✓ or ⚠ + reason).
- **Filters:** All · Failed (tripped/down/stale) · Connectivity problems (unreachable).
- Header summary: total · failed · Registry-stale · unreachable counts.
- Collapses default to sections; expand to units → devices. Failed/unreachable branches auto-expand.

## C. Run the real Registry in the live stack

- **Local (default):** `run_local.py` already runs Registry + orchestrator + projector + console.
  Set `REFINERY_REGISTRY_URL=http://127.0.0.1:8081` on the orchestrator → console shows the real fleet.
- **Cloud Run:** co-locate the Registry. Option (a) run the Registry as a second loopback process in
  the orchestrator container (+ projector), JWT from Secret Manager; orchestrator reads it on
  127.0.0.1. Option (b) keep Cloud Run sim-only; demo the *real* bard-infra via `run_local` locally.

## Open decisions (confirm before build)
1. **Cloud Run scope:** co-locate the real Registry on Cloud Run (the URL becomes truly real, more
   work) **vs** keep Cloud Run sim-only and demo real bard-infra locally (recommended first).
2. **Connectivity-problem definition:** unreachable = section-switch-down OR gateway-down OR
   Registry-stale. Confirm (or add: a node is also unreachable if any hop on its Purdue path is down).
3. **New "Fleet" tab** (vs folding into Investigate) — recommend a dedicated tab.

## Sequencing
1. Backend: Registry client + `/discovery` + `/fleet` (join + connectivity) + tests (mock Registry).
2. Local verify: `run_local.py` → console shows real `active/stale` + connectivity.
3. Frontend: Fleet tab (collapsing tree + filters + summary) + Playwright.
4. (If §C-a) Cloud Run Registry co-location.

Parked (after this): cdn-sim AgentPanel-on-left (Vulcan 5-step) · events-timeline (major events
ticking by) · ISA-101 restyle.
