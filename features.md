# bard-infra — feature backlog

Infrastructure features for the Bard zero-trust fabric. Format per
`shared-rules/process-rules.md §2`: each entry has a short description, date
added, and a status beginning with exactly one of `Open`, `In Progress`, or
`Completed`.

> **Source of detail.** The live BardPro engineering backlog
> (`~/projects/VibeLLamaPhonograph/bardLLMPro/features.md`) holds the full
> design text for the items marked *(migrate)* below. They are listed here by
> name so this repo is the canonical infra index; the verbatim entries migrate
> from bardLLMPro in a follow-up pass (do not duplicate numbering until that
> migration is reconciled).

## Infrastructure

### INFRA-1 — Fabric name resolution (DNS) so endpoints aren't pinned to IPs

- **Added:** 2026-06-13
- **Status:** Open
- **Type:** Infrastructure (not a plugin — *how the platform works*).

**Problem.** Fabric endpoints (Router, Registry, agents, the LokNet front
door) are addressed today by hard-coded `host:port` through the config layer.
When an address changes — DHCP lease, host reimage, cloud redeploy, tailnet IP
reassignment — every pinned reference breaks. Not hypothetical: on 2026-06-13
the `frogstation` GPU node was reimaged, its tailnet IP moved
`100.82.167.91 → 100.92.74.65`, and every config/SSH entry pinned to the old IP
went dead while the **name** `frogstation` kept resolving (Tailscale MagicDNS).

**Feature.** A name-resolution layer so every fabric participant is addressed
by a **stable logical name**, never a raw IP: clients reach the Router by name,
agents register/heartbeat under a name→endpoint mapping, and the public
Router/broker front door has a stable resolvable address that survives backend
IP churn.

**Options to evaluate (design-only):**
- **Mesh-native DNS** — Tailscale **MagicDNS** (already resolves the fleet by
  name today) or Headscale DNS. Cheapest; zero new infra; names stable by
  construction.
- **Registry-backed internal resolver** for the mesh-free **LokNet** path — the
  Registry already holds the authoritative node list; expose name→endpoint
  resolution from it so the broker front door and agents are reachable by name
  without a mesh.
- **Standard DNS / SRV records** for a public Cloud-Run Router front door
  (stable FQDN) so external clients never embed an IP.

**Done-signal.** Router/Registry/agent config accepts logical names; a node
whose IP changes rejoins and is reachable with **no config edit**; a test swaps
a node's address and asserts the fabric still resolves it.

**Decision (2026-06-15, Eddie).** MVP targets **MagicDNS-only** — lean on the
Tailscale MagicDNS that already resolves the fleet by name today (zero new
infra, names stable by construction). This is enough for the home/beachhead
profile. It does **not** cover the mesh-free LokNet path or a public-Router
FQDN; those (registry-backed resolver, managed DNS) are explicitly deferred,
and the longer arc is **self-hosting our own DNS** — see [INFRA-2](#infra-2--self-hosted-fabric-dns-target-state).
Resolves the former (a)/(b) clarifications. Re (c): name resolution sits
**beside** the bardLLMPro liveness/heartbeat work (#54, Completed), not on top
of it.

**MVP deliverable (this repo).** The config that must accept logical names
lives in bardLLMPro (`common/config.py`); the cross-repo wiring is a tracked
follow-up, not MVP. In bard-infra the MVP ships: the frozen name-resolution
**contract**, a startup **validator** (fail-fast when a logical name does not
resolve or a raw fabric IP is pinned), and an **IP-swap regression test**
proving a node that changes address stays reachable by name.

**Demonstrated live (2026-06-16).** The done-signal is met in practice: the
fabric was brought up across the tailnet (Mac + gx10 agents, `edwards-macbook-pro`
+ `gx10`), addressed **by MagicDNS name** with `ENFORCE_PEER_NAME_RESOLUTION=true`
— both registered and a client request **routed to the remote gx10 agent and back**
(echo) over the tailnet. During the same session Tailscale reassigned frogstation's
IP **twice** (re-auth) and **the name never changed**, so name-based access held
with zero config edits — exactly the IP-churn case INFRA-1 exists for. Reproduce:
`bardLLMPro/scripts/tailscale_fleet_up.sh edwards-macbook-pro gx10` +
[`docs/runbooks/tailscale-fabric-demo.md`](docs/runbooks/tailscale-fabric-demo.md).
The schemed-advertised-address validator gap this surfaced is fixed in
bardLLMPro `2f369bf`.

### INFRA-2 — Self-hosted fabric DNS (target state)

- **Added:** 2026-06-15
- **Status:** Open
- **Type:** Infrastructure (post-MVP evolution of INFRA-1).

**Want (Eddie, 2026-06-15):** "eventually want our own dns." MagicDNS is the
MVP because it is zero-infra, but it ties name resolution to Tailscale. The
target state is a fabric-owned resolver so names work on the mesh-free LokNet
path and for a public Router front door, independent of any single mesh
provider. Candidates carried forward from INFRA-1's deferred options: a
**registry-backed internal resolver** (the Registry already holds the
authoritative node list) and/or **managed/standard DNS** (Cloud DNS, Route53,
or self-hosted authoritative) for a stable public FQDN. Design-only until the
MVP lands; sequenced after INFRA-1.

## Migrated from bardLLMPro — canonical infra index

These items are implemented or decided in bardLLMPro; their authoritative
source (ADR / CHANGELOG / contract) lives there. This repo is the canonical
**index**: each entry carries the reconciled status and a source pointer, not a
copy that can drift. (A1 migration reconciled 2026-06-15; the six former
`(migrate)` placeholders are now dated entries below. Source: bardLLMPro at
`~/projects/bard-llm/bardLLMPro/`, frozen contracts under `contracts/`.)

### INFRA-3 — LokNet outbound-agent broker transport

- **Added:** 2026-06-15 · **Status:** Completed (bardLLMPro v1.1.0–v1.3.0)
- **Source:** bardLLMPro #59; ADR-0013; `contracts/broker-link.schema.json`.

Agents hold a persistent **outbound** WebSocket to the Router (`/v1/agent-link`),
so the fabric needs a single public TLS front door and no mesh, port-forwarding,
or inbound agent ports. Slice 1 (frameId-correlated `/infer` dispatch over WS),
slice 2 (registration + heartbeat relay to a private Registry), and slice 3
(Cloud Run deploy recipe) are all done; real-socket smoke test proven (v1.2.1).
Agent opt-in: `BARDPRO_BROKER_ENABLED=true` + `BARDPRO_BROKER_URL=wss://<router>/v1/agent-link`.

### INFRA-4 — Quay image distribution

- **Added:** 2026-06-15 · **Status:** Open (v2; CI/infra, no frozen design yet)
- **Source:** bardLLMPro #53; tied to the weekly UBI rebuild pipeline.

Multi-arch (amd64 + arm64) agent images published to and pulled from Quay, with
Clair vulnerability scanning and cosign signing in the pipeline. Today images
build locally (UBI-9 Podman); the Quay distribution + signing path is designed
but not built. Sequenced for v2.

### INFRA-5 — Valkey control plane

- **Added:** 2026-06-15 · **Status:** Open (v2; deferred decision)
- **Source:** bardLLMPro ADR-0010 (Proposed, deferred to v2); ROADMAP "Walk" tier;
  `contracts/control-plane.openapi.yaml`.

Replace the single-instance JSON-file Registry store with **Valkey** (Apache-2.0
Redis drop-in) as the source-of-truth KV + pub/sub: enables multi-instance
Router/Registry (HA), a LokNet dispatch queue, and persistent agent/device
records. The single-front-door design (Router public, Registry private) depends
on this. Not started; gates multi-instance HA.

### INFRA-6 — Ansible config-management facts

- **Added:** 2026-06-15 · **Status:** Open (enterprise/v2 roadmap; no design yet)
- **Source:** bardLLMPro MEMORY.md (enterprise-only; never ships in the client).

Treat config-management **facts** as infrastructure (host/fleet state), distinct
from any playbook-automation *plugin* that would run on top of the fabric. An
enterprise-profile (Profile B) item; flagged but not designed. Sequenced after
the control plane.

### INFRA-7 — Prometheus metrics + structured logs

- **Added:** 2026-06-15 · **Status:** Completed (bardLLMPro v0.12.0)
- **Source:** bardLLMPro #55; `prometheus-client` 0.25.0.

Unauthenticated `/metrics` (Prometheus format) on Router, Registry, and Agent;
structured JSON logs via `BARDPRO_LOG_FORMAT=json` (default json). Satisfies
rubric dimension 8 (observability) for the shipped fabric.

### INFRA-8 — Registry agent liveness (heartbeat + TTL)

- **Added:** 2026-06-15 · **Status:** Completed (bardLLMPro v0.11.0)
- **Source:** bardLLMPro #54; `contracts/registry.openapi.yaml`.

Agents heartbeat `POST /register` on an interval (`BARDPRO_HEARTBEAT_INTERVAL_S`,
default 15s); the Registry stamps `last_seen` and marks an agent stale past its
TTL (`BARDPRO_AGENT_TTL_S`, default 45s), excluding stale agents from `/pool`
and `/schedule`. INFRA-1 name resolution sits **beside** this, not on top of it.
