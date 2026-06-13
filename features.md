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

**Clarify (fold in when picked up):** (a) is mesh-native DNS enough for the
beachhead, or is the registry-backed resolver required for the mesh-free LokNet
story? (b) public Router — managed DNS (Cloud DNS/Route53) or the mesh name?
(c) does this absorb the bardLLMPro liveness/heartbeat work or sit beside it?

## To migrate from bardLLMPro (names only — reconcile design + status on move)

- **LokNet — outbound-agent broker transport** *(migrate)* — agents hold a
  persistent outbound WS to the Router; single public TLS front door, no mesh /
  port-forwarding. (bardLLMPro #59.)
- **Quay image distribution** *(migrate)* — multi-arch agent images pulled from
  Quay; Clair scanning + cosign signing. (bardLLMPro #53.)
- **Valkey control plane** *(migrate)* — v2 dispatch queue / pub-sub replacing
  the JSON-file store. (bardLLMPro — confirm number on move.)
- **Ansible facts** *(migrate)* — config-management facts as infra (vs. the
  playbook-automation plugin). (bardLLMPro — confirm number on move.)
- **Prometheus metrics + structured logs** *(migrate)* — `/metrics` on
  Router/Registry/Agent; JSON logs. (bardLLMPro #55, done in bardLLMPro.)
- **Registry agent liveness — heartbeat + TTL** *(migrate)* — `last_seen` +
  TTL eviction. (bardLLMPro #54, done in bardLLMPro.)
