Status: In Progress — design capture (Eddie, 2026-06-30); awaiting confirmation before build

# DESIGN — Industrial fabric: legacy vs. bard-infra distributed (the Investigate story)

Author: Jason (from Eddie's rapid-fire direction, 2026-06-30)

The demo's Investigate tab grew from "show a device diagram" into the **bard-infra
industrial pitch**: contrast legacy PLC/SCADA with a distributed, self-discovering,
twin-backed fabric. This doc captures Eddie's stated vision verbatim-in-spirit so nothing
is lost; the build follows once the framing is confirmed.

## What Eddie asked for (in order)
1. Investigate tab = a **circle/network diagram** of the real devices: servers, GUIs
   (HMIs), gateways, PLCs, sensors, valves, switches.
2. **Legacy realism:** no PLC handles more than ~100 control loops (centralized aggregation).
3. **Alternative design:** each sensor/valve has its **own microcontroller running its own
   control loop** (smart edge instrument), instead of a central PLC.
4. Those nodes **cascade up to industrial ARM gateways** that **save sensor/valve state in a
   shared Redis database**.
5. **Simulate faithfully** — store data in **separate areas to simulate failover**.
6. **Digital twin:** when a valve "dies", a twin shows **the state it was in** (last-known
   state survives the device).

## The two architectures (Investigate tab compares them)

### A — Legacy PLC / SCADA (the strawman)
- Sensors/valves hardwired to **PLCs**; each PLC ≤ ~100 control loops.
- PLC → industrial switch → gateway → SCADA/historian (Purdue L0→L3).
- Centralized: a PLC failure darkens all ~100 of its loops; no state retention at the edge;
  control logic is a single point of failure.

### B — bard-infra distributed fabric (the hero)
- **Every sensor/valve = a smart node**: microcontroller + its own local control loop.
- Each node **self-discovers + self-registers** into the bard-infra Registry — *this is the
  self-discovery we already built and proved (116 elements active/stale/active).*
- Nodes **cascade up to industrial ARM gateways** (the edge ARM compute — Gladius lineage).
- ARM gateways **persist every device's state into a shared Redis store**.
- Redis is **replicated across separate areas** → **failover**: lose a gateway/area, another
  serves the state.
- **Digital twin**: device state lives in the store, so when a device dies the twin shows its
  last-known state — the plant never goes blind on a dropped device.

Why B wins (the pitch): resilient (no 100-loop blast radius, area failover), self-organizing
(plug-and-discover), and state-durable (twin survives device death). It *is* bard-infra's
zero-trust self-discovering fabric applied to OT.

## Faithful simulation — what "faithfully" means here
- Model the real data path: device → microcontroller loop → ARM gateway → Redis (replicated
  areas). Not just a static diagram — the state actually flows and persists.
- **Failover demo:** kill a gateway/area; the twin state is still served from a replica.
- **Twin demo:** kill a valve; its last state persists in the store and is shown as the twin.

## Open decisions (confirm before build)
1. **Framing/hero** — two-architecture compare, B (distributed) is the hero. Confirm.
2. **Faithful-sim tech** — real Redis (or fakeredis) with replicated "area" instances vs. an
   in-memory model of replicated areas. Confirm which faithfulness bar.
3. **Build order** — (a) Investigate device "circle diagram" (both architectures, toggle) up
   first so it's visible, then (b) the distributed sim: microcontrollers + ARM gateways +
   Redis areas + twin + failover. Confirm.

## Already in place (foundation)
- Self-discovery into the real Registry (Sprint 3) — Design B's enrollment, done.
- `/netgraph` device topology endpoint (Design A wiring) — committed.
- `/history` trend buffer, `/graph` cascade — committed.
- Linda's ISA-101 HMI style guide (alarm banner, PV/SP/OP, trends, grey canvas) — for the
  console restyle (separate track; see features #11–13).
