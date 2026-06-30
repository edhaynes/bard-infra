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
source .venv/bin/activate            # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
python -m pytest                     # full suite, 100% line+branch (run from demo/)
```

Run the **whole demo** (real bard-infra Registry + orchestrator + fleet projector +
console) with one command:

```bash
python scripts/run_local.py          # add --no-console for backend only
# Console http://127.0.0.1:5175 · Orchestrator :7090 · Registry :8081
```

Try it in the console: **Bring up** → watch utilities-first cascade to 19/19 units →
**Inject** a "Gas release → SIS trip" on `U-840` (FCC) → see it trip + 4 downstream
units cascade red → **Resolve** → **Bring down** (leaf-first, utilities last).

Container (Cloud Run parity, UBI base):

```bash
podman build -f deploy/Containerfile -t refinery-demo .
podman run --rm -p 8080:8080 refinery-demo   # dashboard at http://localhost:8080
```

See `deploy/DEPLOY.md` for Cloud Run.

## Configuration

Copy `.env.example` to `.env` (gitignored). Never commit a real `REFINERY_JWT_SECRET`.

## Status

**All 8 sprints complete** (2026-06-30). Backend 100% branch-covered (92 tests);
self-discovery proven on the real Registry; console built + run-verified
(`docs/screenshots/`) — awaiting Eddie's visual sign-off; container builds + runs. See
`PLANS.md`, `JOURNAL.md`.
