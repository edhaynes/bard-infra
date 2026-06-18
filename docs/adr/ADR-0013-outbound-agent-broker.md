# ADR-0013: Outbound-agent broker transport (WebSocket) — drop the Tailscale dependency

Date: 2026-06-10
Status: Accepted (v2 — Walk; first post-MVP feature)
Author: Jason draft; scoped by Eddie (2026-06-10, root features.md #59)
Roadmap tier: v2 — Walk
Relates to: ADR-0002 (no-mesh MVP — this is the v2 "pluggable transport" it promised,
delivered without a mesh at all), ADR-0001 (wire protocol — envelopes unchanged),
ADR-0010 (Valkey control plane — the broker's dispatch seam is where pub/sub lands),
ROADMAP.md §v2, root features.md #59

## Context

The v1 Crawl MVP routes inbound: the Router dials each agent's `/infer` over HTTPS at
the address the agent registered. That requires every agent to be **reachable** from the
Router — fine on one LAN (ADR-0002), but across NAT/firewalls it forced the demo fleet
onto Tailscale, and the Cloud Run node could not be dialed at its registered address at
all, leading to the registration-by-proxy hack (v0.10.0). ADR-0002 deferred
reachability to v2 as "mesh as a pluggable transport"; a mesh, however, is not the only
way to get reachability — inverting the connection is cheaper and vendor-free.

## Decision

Agents **optionally** hold a **persistent outbound WebSocket** to the Router
(`/v1/agent-link`, authenticated with the same JWT / `TokenVerifier` seam). The Router
keeps an in-memory map of live links (one per `agentId`; a new connection replaces the
old). When `POST /v1/message` arrives for a `targetAgent` with a live link, the Router
forwards the request **down that link** as a correlated frame (request-id correlation,
`request_timeout_s` deadline → `502 agent_unavailable, retry: true`) and relays the
correlated response. **No live link → the existing direct HTTP dial path runs
unchanged.**

The change is **fully additive**: direct mode keeps working, the default is unchanged
(`BARDPRO_BROKER_ENABLED=false`), the frozen protocol envelopes (`Request` / `Response`
/ `Error`) ride inside the new frames untouched, and the v1 OpenAPI surfaces are not
modified — the frame contract lives in a new `contracts/broker-link.schema.json`.

Rationale:

- **Only outbound 443 needed.** Every node — laptop behind NAT, Cloud Run container,
  homelab box — needs nothing but an outbound TLS connection to one public Router
  endpoint (Let's Encrypt or Cloud-Run-hosted). No mesh, no port-forwarding, no
  Tailscale, no vendor control plane.
- **Fixes the Cloud-Run-node hack.** A scale-to-zero node that cannot accept inbound
  dials simply holds the link open; registration-by-proxy dies.
- **Converges with v2 Valkey dispatch (ADR-0010).** The broker introduces exactly the
  dispatch seam ("router hands work to a link, awaits a correlated reply") that the
  Valkey queue/pub-sub control plane will later sit behind.

Transport choice — **WebSocket**, not SSE and not gRPC:

- **Over SSE:** the link must be bidirectional (Router pushes work down; agent pushes
  responses up on the same connection). SSE is server→client only and would still need
  a separate upstream channel.
- **Over gRPC:** zero new dependencies. Starlette/FastAPI WebSocket support is already
  in-tree — `uvicorn[standard]` pins `websockets` (16.0 in `uv.lock`, verified), which
  also provides the agent-side client. gRPC would add `grpcio`/codegen for no MVP gain.

## Consequences

- **Connection-manager state lives in the Router process** — same single-instance
  constraint the JSON-file registry already imposes on v1. Multi-instance routers need
  the v2 Valkey control plane (ADR-0010) to share/route links; out of scope here.
- **Agents own reconnect:** exponential backoff with a cap, link failures are logged
  and never fatal (mirrors the heartbeat loop's stance). The `/register` heartbeat
  (feature #54) is untouched and stays the liveness authority — a served broker frame
  is incidental activity, not a replacement signal.
- **Additive contract change:** new `broker-link.schema.json` (hello / hello_ok /
  infer_request / infer_response / infer_error frames); frozen v1 schemas and OpenAPI
  files unmodified.
- A replaced link is closed by the Router; in-flight dispatches on a dropped link fail
  fast as `502 agent_unavailable, retry: true` rather than waiting out the timeout.

## Alternatives considered

- **Tailscale/Headscale mesh (ADR-0002's original v2 plan).** Solves reachability but
  keeps a vendor or a self-hosted control plane, WireGuard clients on every node, and
  does nothing for Cloud Run. Headscale (~2–3 days) remains a rung if a full network
  layer is ever needed; the broker makes it unnecessary for dispatch.
- **SSE + upstream POSTs.** Two half-channels to correlate and keep alive; strictly
  worse than one duplex socket.
- **gRPC bidirectional streaming.** Clean semantics but a new heavyweight dependency
  and codegen step against CLAUDE.md §13; rejected while the stdlib-adjacent WS path
  is already in the lockfile.
- **Long-polling.** No persistent state but high latency and racy timeout semantics;
  rejected.

## Follow-up note — slice 2 (single front door), v1.2.0, 2026-06-10

Slice 1 (above) moved **dispatch** onto the link. Slice 2 (PLAN_loknet) moves
**registration + heartbeat** onto it too, so the Router becomes the only public
endpoint and the Registry needs no public bind in LokNet mode. This note records
the slice-2 shape; the slice-1 decision body is unchanged.

- **Register/heartbeat over the link (additive frames).** When
  `BARDPRO_BROKER_ENABLED=true`, the agent — instead of POSTing the Registry —
  sends a `register` frame right after `hello_ok` and `heartbeat` frames on the
  `heartbeat_interval_s` cadence (identical body; a heartbeat *is* a `/register`
  refresh, so `lastSeen`/TTL/stale semantics from feature #54 are unchanged). The
  Router relays each to the Registry's existing `/register` via the same
  `RegistryClient` abstraction it already uses for lookups (a new `register`
  method on that seam). New frames in `broker-link.schema.json`: `register`,
  `heartbeat`, `registered` (best-effort ack); frozen v1 schemas untouched.
- **Identity binding (security; bug #54 boundary).** The relay is **bound to the
  `agentId` the link authenticated as in its `hello`** — any `agentId` carried in
  a register/heartbeat frame is ignored (the contract forbids one via
  `additionalProperties:false`, and `build_relay_body` re-asserts it). A
  register-over-link therefore **cannot** claim another agent's identity. This
  does *not* fix bug #54 (the `hello` JWT `sub` is still not cross-checked against
  the claimed `agentId`) but it does not widen it: register-over-link trusts
  exactly the same established identity the link already accepted, no fresher.
- **advertisedAddress is the link, not a dialable host.** In broker mode the
  Router reaches the agent down the link, never by dialing an address, so the
  agent omits `advertisedAddress` and the Router synthesizes the sentinel
  `broker://<agentId>`. Placement/pool key off `powerProfile`/`capabilities`/
  `status`, never the address, so the sentinel is inert; `/v1/message` always
  prefers the live link over the registry address anyway.
- **No second liveness path.** A dropped link is not separately detected — the
  agent simply stops heartbeating and goes `stale` by the normal TTL, then leaves
  `/pool` and `/schedule`. Verified by test (`dropped link → stale via TTL`).

### LokNet deployment shape (loopback Registry, public Router)

Direct mode (default) is unchanged: agents POST `/register` to a reachable
Registry. **LokNet mode** runs the Registry on loopback behind the Router:

```
                       outbound wss:// 443 only
   agent (NAT/Cloud Run) ───────────────────────────►  Router  (PUBLIC)
     BROKER_ENABLED=true                                  │  relays /register
     SELF_REGISTER=true                                   ▼  over RegistryClient
                                                       Registry (127.0.0.1:8081,
                                                        no public bind needed)
```

- Router: the only public endpoint (Cloud Run / Let's Encrypt). Serves
  `/v1/message` (public) and `/v1/agent-link` (the WS front door).
- Registry: bind `BARDPRO_REGISTRY_HOST=127.0.0.1` (or a private network only the
  Router can reach). Nothing forces a public bind — the Router calls its existing
  HTTP endpoints in-cluster/loopback. No behavior change in the Registry itself.
- Agents: set `BROKER_ENABLED=true`, `BROKER_URL=wss://<router>/v1/agent-link`,
  `SELF_REGISTER=true`. They never address the Registry directly.

Single-instance still applies (in-memory link map + JSON-file registry); the
Valkey control plane (ADR-0010) lifts that for multi-instance routers later.
