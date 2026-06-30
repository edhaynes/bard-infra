# Refinery Self-Discovery Demo

A refinery stood up in seconds by **self-discovery**: every field element (sensor,
valve, PLC, switch, gateway, workstation) self-registers into the **real bard-infra
Registry** the moment it powers on, and a management **console** renders the live plant.
From the console an operator runs the two critical operations — **bring-up** and
**bring-down** — and the demo **injects and handles failures**.

Topology is modeled on **ExxonMobil Baytown** (public data only; synthetic element tags).

> Part of [bard-infra](../README.md). Public repo — synthetic/public data only, no
> customer/site/commercial material, secrets only via env / Secret Manager.

## Architecture (3 tiers)

| Tier | What | Where |
|---|---|---|
| Registry | Real bard-infra Registry — discovery + liveness (active/stale = online/offline) | bard-infra `registry/` (unchanged) |
| Orchestrator | New sim — telemetry, bring-up/down sequencer, fault propagation; projects every element into the Registry | `demo/refinery/` |
| Console | Re-themed cdn-sim / demo-console — joins Registry identity+liveness with orchestrator telemetry | `demo/console/` |

Element identity, classification, and liveness are **real fabric** (heartbeat → stale =
offline). Live process numbers are the orchestrator overlay, joined by `agentId`.

## Ports

| Port | Service |
|---|---|
| 7090 | Orchestrator API (`REFINERY_API_PORT`) |
| 8081 | bard-infra Registry (local default) |
| 5175 | Console (Vite dev) |

## Quick start

```bash
cd demo
uv venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
python -m pytest                 # full suite, 100% line+branch
```

Running the full local demo (Registry + orchestrator + console) lands in Sprint 7
(`scripts/run_local.sh`); Cloud Run is Sprint 8. See `PLAN_refinery_demo.md`.

## Configuration

Copy `.env.example` to `.env` (gitignored). Never commit a real `REFINERY_JWT_SECRET`.

## Status

See `PLANS.md`, `JOURNAL.md`. Sprint 1 (frozen topology contract) is complete.
