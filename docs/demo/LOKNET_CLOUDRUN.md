# LokNet on Cloud Run — public Router, mesh-free agents

> Feature #59 / ADR-0013, slice 3 (v1.3.0). **Authored, not auto-deployed** —
> the public deploy is Eddie's to run. This runbook is the recipe; the proof
> that the path works on real sockets is `scripts/smoke_broker.py` (loopback).

## What this gives you

A **single public front door** — the Router on Google Cloud Run — and nothing
else exposed. Agents (a laptop behind NAT, a GPU box, another cloud) **dial
out** to the Router's `/v1/agent-link` WebSocket on **443 only**:

- **No Tailscale**, no Headscale, no mesh client, no inbound port, no public
  agent address. The agent needs only outbound 443.
- The agent **registers and heartbeats over that link** (slice 2 single front
  door): the Router relays each frame to the Registry's `/register`. The
  **Registry stays private** behind the Router (loopback / private network) and
  is never publicly bound.
- Clients `POST /v1/message` to the Router; if the target agent holds a live
  link, the request is dispatched **down the link** and the completion comes
  back the same way (slice 1). No registry address is dialed.
- **Cloud Run terminates TLS** (automatic, managed cert), so the public hop is
  HTTPS/WSS with zero cert plumbing on our side.

```
  remote agent (NAT / other cloud)              CLIENTS
     BARDPRO_BROKER_ENABLED=true                   │ POST /v1/message
     BARDPRO_SELF_REGISTER=true                    ▼
            │  outbound wss 443            ┌──────────────────────┐
            └────────────────────────────►│  Router (Cloud Run)  │  PUBLIC, TLS by Cloud Run
                                          │  /v1/agent-link  ◄───┘  single front door
                                          │  /v1/message
                                          │       │ RegistryClient (loopback)
                                          │       ▼
                                          │  Registry (127.0.0.1) │  PRIVATE
                                          └──────────────────────┘
```

## Prerequisites

- A GCP project with billing, and `gcloud` authenticated (`gcloud auth login`).
- `podman` (preferred) or `docker`, **or** use Cloud Build (`BUILDER=gcloud`,
  no local engine needed).
- The JWT signing secret stored in **Secret Manager** (value never in source):

  ```bash
  printf '%s' "$BARDPRO_JWT_SECRET" | gcloud secrets create bardpro-jwt-secret \
      --project=<project> --data-file=-
  ```

## Deploy

```bash
PROJECT=<project> REGION=us-central1 \
    bash scripts/deploy_loknet_router.sh
```

The script is **idempotent and parameterized** (no hardcoded project id). It:

1. ensures the Artifact Registry repo exists (`describe || create`);
2. checks the Secret Manager secret exists (fails loudly with the create
   command if not — it never handles the secret value);
3. builds + pushes `router/Containerfile.cloud` (UBI9, non-root, runs
   `uvicorn router.main:app` on `$PORT`, TLS terminated by Cloud Run);
4. `gcloud run deploy` with **`--min-instances=1 --max-instances=1`**, the JWT
   via **`--set-secrets`** (not plain env), `--allow-unauthenticated`, and
   `--timeout=3600`.

On success it prints the public URL and the exact env to point a remote agent
at it. Re-running redeploys in place.

> **Override knobs** (all env vars): `SERVICE`, `REPO`, `IMAGE_TAG`,
> `SECRET_NAME`, `BUILDER`. See the header of `scripts/deploy_loknet_router.sh`.

## Point a remote agent at the public Router

On the remote box — **no Tailscale, no inbound** — set three env vars and run
the agent. The agent dials out, registers over the link, and serves inference:

```bash
BARDPRO_BROKER_ENABLED=true \
BARDPRO_BROKER_URL=wss://<router-host>/v1/agent-link \
BARDPRO_SELF_REGISTER=true \
BARDPRO_JWT_SECRET=<same-secret> \
    uvicorn agent.main:app --host 0.0.0.0 --port 8444
```

`wss://` is required (the config layer rejects `ws://` unless
`BARDPRO_ALLOW_INSECURE_HTTP=true` — and over the public internet you never
want that). The agent presents the same self-minted JWT it would use on a
direct `/register`; the Router binds the registration to the link's
authenticated `agentId`.

## The 60-minute WebSocket cap — and why it's fine

**Cloud Run forcibly closes any single WebSocket after ~60 minutes** (request
timeout ceiling). That is not a failure mode for LokNet: when the link is
closed, the agent's **slice-1 reconnect loop** (`agent/broker.py`) catches the
drop, backs off (`BROKER_BACKOFF_INITIAL_S` → `BROKER_BACKOFF_MAX_S`,
exponential, reset on a good handshake), and re-establishes the link — then
re-sends its `register` frame and resumes heartbeats. The deploy sets
`--timeout=3600` so the cap is the full hour rather than a shorter default; the
reconnect makes the ceiling **survivable, not load-bearing**. A brief gap
during reconnect is covered by the normal heartbeat TTL (3× interval), so the
agent does not flap to `stale`.

> This is exactly the behavior `scripts/smoke_broker.py` exercises in miniature:
> when the Router shuts down it closes the link (1012) and the agent logs one
> `broker link down, reconnecting` — the loop doing its job.

## Single-instance constraint

`--min-instances=1 --max-instances=1` is **required**, not a cost choice. The
Router holds the live agent-link map **in process memory** (and, in LokNet
mode, the in-process Registry too). A second instance would not see the first
instance's links, so a client routed to it would `502` on a target that is
actually connected elsewhere. The **v2 Valkey control plane (ADR-0010)** moves
link/registry state out of process and lifts this to multi-instance HA; until
then, one instance is the source of truth. `min=1` also keeps the link warm
(no cold-start dropping established agent connections).

## Registry reachability

The Router reaches the Registry over `RegistryClient`. In this single-instance
recipe the Registry runs **private to the Router** — co-located on loopback
(`BARDPRO_REGISTRY_HOST=127.0.0.1`, the Containerfile default) or on a private
network only the Router can see. It is **never publicly bound**. (Running the
Registry as a loopback co-process inside the same Cloud Run container, or as a
private service the Router dials, are both valid; the Router code is unchanged
either way.)

## The Chris demo is NOT rewired to this

Per **PLAN_loknet decision 3**, the Chris demo **stays on the verified
Tailscale path**. LokNet/Cloud Run is the mesh-free *alternative transport*,
proven separately on real sockets (`smoke_broker.py`) and authored here for
Eddie to deploy. It may appear as an optional sixth demo beat **only after a
boringly-stable dry run** — it does not replace the Tailscale topology the demo
runs on today.

## Teardown

```bash
gcloud run services delete <service> --project=<project> --region=<region>
```

The image in Artifact Registry and the Secret Manager secret persist (delete
separately if you want a clean slate).
