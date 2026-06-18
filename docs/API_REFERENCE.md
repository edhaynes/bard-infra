# Bard — Backend API Reference

**Applies to:** v1.3.1 · branch `claude/laughing-bell-57o15u`
**Status of this document:** accurate to the code and the frozen contracts as of this
version. Every claim below was verified against `contracts/` and the FastAPI apps in
`router/`, `registry/`, and `agent/` (plus the broker manager `router/broker.py` and the
agent link client `agent/broker.py`). Where the code and an external/aspirational
description disagree, this document follows the **code**, and the disagreement is called
out explicitly (see *Known gaps & caveats*).

> **The backend API is the product** (ADR-0014). Bard *is* the Router/Registry/
> Agent backend and its frozen wire contract. **Maude** (the claudeTalk iOS app) is the
> **worked example client** — one consumer of this API, **not "the client"** (ADR-0014
> refines ADR-0011). Any conformant client — Maude, the demo console, a raw `curl`, an
> agent's outbound link — speaks exactly the surface documented here. The protocol stays
> client-agnostic (ADR-0001).
>
> **Audience / profiles (ADR-0014).** The same backend ships in two deployment profiles
> selected by config, not by code fork:
> - **Profile A — Ad-hoc (home power user)** — *the first product MVP*. An ad-hoc network
>   of the user's own devices, trust implicit, **zero mandatory cloud**: the whole fleet
>   runs on a home LAN / self-hosted box. The LokNet broker (§3.5) is *optional* and, when
>   used, points at a **self-hosted** Router. This reference **leads its examples with the
>   self-hosted / local path** for that reason.
> - **Profile B — Managed (enterprise)** — adds a management console, strict device
>   onboarding, mTLS/zero-trust, and turns the Router into a policy-enforcement MITM. Same
>   API, stricter trust tier. Out of scope for the v1 surface below except where noted.

---

## 1. Overview

### 1.1 The three services (+ the broker front door)

| Service | Role | Default bind | Source |
|---|---|---|---|
| **Router** (a.k.a. Talk Service) | Public front door. Validates the JWT, rejects voice, then either **dispatches down a live broker link** (§3.5) or resolves `metadata.targetAgent` via the Registry and forwards over a direct HTTPS dial; relays the JSON response. Also hosts the `/v1/agent-link` WebSocket. | `127.0.0.1:8443` | `router/app.py`, `router/broker.py`, `router/clients.py` |
| **Registry** | Maps `agentId → reachable address` plus advertised capacity/liveness. Single-instance, JSON-file persisted (MVP). In LokNet mode it can bind to loopback behind the Router (§3.5.6). | `127.0.0.1:8081` | `registry/app.py`, `registry/store.py` |
| **Agent** | Receives a forwarded `Request` (over `POST /infer` **or** down its outbound broker link), runs the inference engine, returns a `Response`. Optionally holds a persistent outbound WebSocket to the Router. | `127.0.0.1:8444` | `agent/app.py`, `agent/broker.py`, `agent/engine.py` |

Default ports come from `common/config.py` (`router_port=8443`, `registry_port=8081`,
`agent_port=8444`). Default host is `127.0.0.1`. The frozen-contract OpenAPI files
(`contracts/router.openapi.yaml` etc.) declare `https://localhost:<port>` servers — TLS
is the default transport (see §1.4).

### 1.2 Request lifecycle (two dispatch paths)

A single client call walks the fleet like this (`router/app.py::post_message`):

```
client ──POST /v1/message (JWT bearer + metadata.authToken)──▶ Router
  Router: verify JWT (metadata.authToken)                → 401 unauthorized on failure
  Router: reject type=voice                              → 501 unsupported_type
  Router: does targetAgent hold a LIVE broker link?
    ├─ YES (link-first dispatch, §3.5) ──infer_request frame──▶ Agent (down its link)
    │     Agent: serve through the SAME engine as /infer
    │     Agent ──infer_response / infer_error (same frameId)──▶ Router
    │     (any infer_error / timeout / link loss → 502 agent_unavailable, retry=true)
    └─ NO (direct-dial path, unchanged from v1)
          Router: GET /agents/{targetAgent} on the Registry  → 404 not_found if unknown
                                                              → 502 agent_unavailable if Registry down
          Router ──POST /infer (forwards the same Request)──▶ Agent
          Agent: verify the same JWT                         → 401 unauthorized on failure
          Agent: reject type=voice                           → 501 unsupported_type
          Agent: engine.infer(request)                       → 502 inference_failed (retry) on engine error
  Agent ──Response──▶ Router ──Response──▶ client (200)
```

**Link-first dispatch:** if `broker is not None and broker.has_link(targetAgent)`, the
Router prefers the live link and **never consults the Registry address** for that call
(`router/app.py`). With `broker=None`, or no live link for the target, the Router runs the
v1 direct-dial path exactly as before — the broker is purely additive (ADR-0013).

The direct-dial path forwards the **same** `Request` body it received (including
`metadata.authToken`) to the agent's `/infer`; the agent re-verifies that token
independently. There is no separate Router→Agent credential in the MVP. On the link path
the agent re-verifies the forwarded `request.metadata.authToken` identically
(`agent/broker.py::serve_frame`).

### 1.3 Frozen-contract discipline

The wire contract is frozen and lives in `contracts/`:

- `protocol.schema.json` — the JSON envelope (`Request`/`Response`/metadata/`ToolCall`/`ToolResult`/`Error`), shared by all services **and ridden unchanged inside broker frames**.
- `router.openapi.yaml`, `registry.openapi.yaml`, `agent.openapi.yaml` — per-service HTTP surfaces.
- `power-profile.schema.yaml` — per-agent resource ceiling advertised at registration.
- `broker-link.schema.json` — **additive v1.1/v1.2 contract** (ADR-0013): the JSON text
  frames on the agent's outbound WebSocket to the Router (`/v1/agent-link`). The frozen
  v1 HTTP OpenAPI surfaces are **not modified**; the broker is a new, separate contract.

The schema is **canonical**; the Pydantic models in `common/protocol.py` and
`common/power.py` are its Python projection. *"If the two ever disagree, the schema wins"*
(`common/protocol.py` docstring). Changes are additive-only and are made **in `contracts/`
first**, then re-propagated — never patched inside a service lane. See §9.

### 1.4 Wire conventions

- **Encoding:** JSON request and response bodies (`application/json`); JSON **text frames**
  on the broker WebSocket.
- **Field names:** **camelCase on the wire** (`targetAgent`, `authToken`, `sessionId`,
  `agentId`, `toolCalls`, `powerProfile`, `frameId`, `advertisedAddress`). The Pydantic
  models keep camelCase field names to match the wire exactly (`common/protocol.py`).
- **Transport:** HTTPS by default; **WSS by default** for the broker link. The Router dials
  the Registry and agents over TLS; an agent address with no scheme is dialed as `https://`
  (§8.6). Plain HTTP (`registry_scheme=http`) and plain `ws://` (broker) are explicit,
  validated opt-ins gated on `allow_insecure_http=true` (`common/config.py::_validate`,
  `_validate_broker_url`).
- **Auth:** Bearer JWT — see §2.
- **IDs:** `Request.id` / `Response.id` are UUIDs (`protocol.schema.json#/$defs/Uuid`,
  the canonical 8-4-4-4-12 pattern). `Response.id` echoes `Request.id`. `frameId` is a
  separate, opaque Router-generated correlation id on the broker link (§3.5.3).
- **Timestamps:** RFC 3339 / ISO 8601 UTC (`...Z`), per `#/$defs/Timestamp`.

---

## 2. Authentication

### 2.1 Mechanism

All authenticated surfaces expect a **Bearer JWT**. The default verifier is `JwtVerifier`
(`common/auth.py`):

- **Algorithm:** `HS256` (HMAC) by default (`jwt_algorithm`, configurable).
- **Secret:** injected from config (`BARDPRO_JWT_SECRET`), **required at runtime** — the
  Router and Agent fail fast at startup if it is unset (`*/main.py`,
  `JwtVerifier.from_config`). Never hardcoded.
- **Issuer:** `jwt_issuer` defaults to `bardllm-pro`. Because the default is non-empty,
  **the `iss` claim is verified by default** — a token minted with a different `iss` is
  rejected.
- **Claims:** the MVP mints `{ sub, iss, iat, exp }` (`agent/register.py::mint_agent_token`).
  `exp` is honored by PyJWT — expired tokens are rejected.
- **Swappable verifier:** `TokenVerifier` is a `runtime_checkable` `Protocol`. The
  post-MVP PQ-identity verifier (Profile B / TRUST_MODEL) drops in behind the same
  interface without touching call sites — including the broker handshake, which uses the
  **same `TokenVerifier` seam** as `/v1/message` (`router/broker.py::handle_agent_link`).

### 2.2 Where the token goes (carriers)

Distinct token-carrying surfaces exist:

| Surface | Token carrier | Code that reads it |
|---|---|---|
| `POST /v1/message` (Router) | **`metadata.authToken`** in the JSON body | `router/app.py` reads `request.metadata.authToken` |
| `POST /infer` (Agent) | **`metadata.authToken`** in the JSON body | `agent/app.py` reads `request.metadata.authToken` |
| Broker link infer frames (Agent) | **`metadata.authToken`** inside the framed `Request` | `agent/broker.py::serve_frame` verifies it |
| Broker `hello` frame (Router) | **`authToken`** field of the hello frame | `router/broker.py::handle_agent_link` |
| `POST /register`, `GET /agents`, `GET /agents/{id}`, `GET /pool`, `GET /schedule` (Registry) | **`Authorization: Bearer <jwt>` header** | `registry/app.py::_bearer` |

> **Practical note on `/v1/message`:** the *contract* (`router.openapi.yaml`) declares
> `bearerAuth` (an `Authorization` header) for the endpoint, and the schema **requires**
> `metadata.authToken` in the body. The **MVP Router code verifies the body token
> (`metadata.authToken`), not the header.** A correct, future-proof client (Maude does
> this) sends **both** — the `Authorization: Bearer` header *and* `metadata.authToken` —
> so it satisfies the contract today and survives a Router that later checks the header.
> The Registry endpoints, by contrast, verify the **header** and ignore the body. The same
> body-vs-header split applies to the Agent's `/infer` (`agent.openapi.yaml` declares
> `bearerAuth`; the agent reads the body token). These splits are flagged in §10.

> **Broker hello note (slice 2 / bug #54).** The `hello` frame carries `agentId` **and**
> `authToken`, both verified, but the verifier checks only that the JWT is valid — it does
> **not** cross-check the JWT `sub` against the claimed `agentId`. Any register/heartbeat
> the agent then sends over the link is **bound to the `agentId` the link authenticated as
> in its hello** (`build_relay_body` ignores any frame-supplied id), so register-over-link
> cannot impersonate *another* agent — but the hello `sub`↔`agentId` binding itself is the
> still-open part of bug #54 (§10).

### 2.3 Unauthenticated endpoints

`GET /healthz`, `GET /version`, and `GET /metrics` are **unauthenticated** on every HTTP
service (`/metrics` is a standard Prometheus scrape, same trust level as `/healthz` —
`common/metrics.py`). The contract documents `/metrics` as an "unauthenticated scrape,
like /healthz". The broker WebSocket itself is **not** unauthenticated — the very first
frame must be a valid `hello` or the socket is closed (§3.5.2).

---

## 3. Router API

Base URL (default): `https://127.0.0.1:8443`. Source: `router/app.py`, `router/broker.py`,
`router/clients.py`. Contract: `contracts/router.openapi.yaml` (HTTP) +
`contracts/broker-link.schema.json` (the WS link).

### 3.1 `POST /v1/message`

Send a text message to an agent. Voice is accepted by the schema but returns `501`.

**Request body** — a `Request` (`protocol.schema.json#/$defs/Request`):

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "type": "text",
  "content": "Hello, fleet.",
  "metadata": {
    "targetAgent": "agent-local",
    "authToken": "<JWT>",
    "sessionId": "optional-session-id",
    "timestamp": "2026-06-10T13:00:00Z"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (UUID) | yes | 8-4-4-4-12 UUID. Echoed in the response. |
| `type` | `"text"` \| `"voice"` | yes | `voice` → `501` in the MVP. |
| `content` | string | yes | UTF-8 text (base64 audio when `type=voice`, but voice is 501). |
| `metadata.targetAgent` | string | yes | `agentId` to resolve (via a live link first, else the Registry). |
| `metadata.authToken` | string | yes | JWT. Validated by the Router; MUST NOT be logged. |
| `metadata.sessionId` | string | no | Opaque; relayed to the agent and echoed back. |
| `metadata.timestamp` | string (RFC 3339) | no | Client-supplied; not validated against drift in the MVP. |

`metadata` forbids unknown keys (`additionalProperties: false` / Pydantic `extra="forbid"`).

**Response `200`** — a `Response` (`protocol.schema.json#/$defs/Response`):

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "type": "text",
  "content": "echo: Hello, fleet.",
  "metadata": {
    "agentId": "agent-local",
    "sessionId": "optional-session-id",
    "toolCalls": [{ "name": "echo", "arguments": { "content": "Hello, fleet." } }],
    "toolResults": [{ "name": "echo", "output": "Hello, fleet." }]
  }
}
```

`toolCalls`/`toolResults` are present only when the engine emits them (the `echo` engine
does; `llamacpp` does not). The Router relays the agent's body verbatim via
`model_dump(exclude_none=True)` on **both** dispatch paths, so `null` fields are omitted.

**Error responses** (all use the structured `Error` envelope, §7):

| Status | `error` code | `retry` | When |
|---|---|---|---|
| `400` | `bad_request` | — | Request body fails schema validation (`RequestValidationError`). |
| `401` | `unauthorized` | — | `metadata.authToken` missing/invalid/expired/untrusted. |
| `404` | `not_found` | — | `targetAgent` not in the Registry (**direct-dial path only** — never reached when a live link exists). |
| `501` | `unsupported_type` | — | `type=voice` (detail: `"voice not supported in MVP"`). |
| `502` | `agent_unavailable` | `true` | Registry unreachable, the agent unreachable / returned ≥ 400 (direct-dial), **or** a broker dispatch failed: missing/dropped link, send failure, agent-reported `infer_error`, malformed reply, or timeout (`request_timeout_s`). |

> **Resolution order matters:** the Router checks **auth → voice → (live link? dispatch :
> registry lookup → agent forward)**. So a voice request with a *valid* token returns
> `501`; on the **link path** an unknown target simply has no link and falls through to the
> registry lookup, where an unknown `targetAgent` returns `404`. A `502 agent_unavailable`
> is the single catch-all for *every* downstream failure on *either* path (all set
> `retry=true`); the client cannot distinguish "Registry down" from "agent down" from
> "broker link dropped" by status code alone. This is deliberate parity: a broker
> `infer_error` maps to the same `502 agent_unavailable, retry:true` the direct dial would
> have produced (`router/broker.py::dispatch`).

### 3.2 `GET /healthz`

Liveness probe. Unauthenticated. Returns `200` with `{"status":"ok"}` (`router/app.py`;
the contract documents only `200 OK`).

### 3.3 `GET /version`

Unauthenticated. Returns `200` with `{"version":"<X.Y.Z>"}` from
`common/version.__version__` (the canonical `VERSION` file). The OpenAPI summary describes
this as "`vX.Y.Z + sha + date`"; the **code returns just `{"version": "<X.Y.Z>"}`** — the
SHA and build date are not embedded in the JSON in this version (flagged in §10).

### 3.4 `GET /metrics`

Unauthenticated Prometheus exposition (`text/plain`, `CONTENT_TYPE_LATEST`). Added by
`common/metrics.instrument`. Series:

- `http_requests_total{service,path,status}` — request count by service, matched route
  template, and status.
- `http_request_duration_seconds{service,path}` — request duration histogram.

The Router additionally exposes the broker-link families (`router/main.py` wires a
`BrokerMetrics`):

- `broker_link_active{agentId}` — gauge, `1` while an agent holds a live outbound link, `0`
  otherwise.
- `broker_dispatch_total{agentId,outcome}` — counter, `outcome ∈ {ok, error, timeout,
  disconnected, send_failed}`.

`/metrics` is excluded from its own instrumentation. `service` label is `"router"`.

### 3.5 Broker / `/v1/agent-link` (LokNet outbound-agent link) — **shipped, opt-in**

The **LokNet broker** is a first-class, shipped API surface (ADR-0013; root `features.md`
#59). It lets an agent dial *out* to the Router over a single persistent **WebSocket**, so
the Router can push inference work *down* the link instead of dialing the agent inbound.
This removes the v1 requirement that every agent be reachable from the Router (no mesh, no
Tailscale, no port-forwarding — only outbound 443). It is **additive and default-off**:
with `broker=None` the Router is exactly the v1 surface, and the agent only dials out when
`BARDPRO_BROKER_ENABLED=true`.

The Router **always serves** `/v1/agent-link` when a `BrokerLinkManager` is injected
(`router/main.py` injects one unconditionally); whether any agent *uses* it is the
agent-side opt-in. Frame shapes are contract: `contracts/broker-link.schema.json`. The
frozen `Request`/`Response`/`Error` envelopes ride **inside** these frames unchanged.

> **Profile A note:** in the home-power-user MVP the broker is *optional* and, when used,
> points at a **self-hosted** Router (`BARDPRO_BROKER_URL=wss://<your-box>/v1/agent-link`).
> Cloud Run is one rendezvous *option*, never required (ADR-0014).

#### 3.5.1 Endpoint

`GET /v1/agent-link` — **WebSocket** (WSS by default). One link per `agentId`. **Note:**
this path lives **only** in `broker-link.schema.json`; it is intentionally **not** in
`router.openapi.yaml` (the v1 HTTP OpenAPI was frozen and left unmodified — §10).

#### 3.5.2 Handshake (`hello` → `hello_ok`)

After the socket connects, the **agent sends the first frame**, a `hello`:

```json
{ "type": "hello", "agentId": "agent-local", "authToken": "<JWT>" }
```

The Router verifies `authToken` with the **same `TokenVerifier`** `/v1/message` uses, then:

- replies `{ "type": "hello_ok" }` — the link is live; or
- **closes the socket** with a close code on failure (§3.5.5).

`HelloFrame` requires `type`/`agentId`/`authToken` (all non-empty), `additionalProperties:
false`. `HelloOkFrame` is just `{ "type": "hello_ok" }`.

#### 3.5.3 Dispatch & `frameId` correlation (slice 1)

Once live, the Router pushes work down the link as an `infer_request` frame carrying a
**unique, Router-generated `frameId`**:

```json
{
  "type": "infer_request",
  "frameId": "9f2c…",
  "request": { /* a frozen protocol.schema.json Request */ }
}
```

The agent serves it through the **same `InferenceEngine`** as `POST /infer` — same token
re-verification, same voice rejection, same error mapping (`agent/broker.py::serve_frame`)
— and replies with the **same `frameId`**:

- success: `{ "type": "infer_response", "frameId": "9f2c…", "response": { …Response } }`
- failure: `{ "type": "infer_error", "frameId": "9f2c…", "error": { …Error } }`

`frameId` is the correlation key: concurrent dispatches on one link may **interleave**, and
the Router matches each reply to its pending future by `frameId`
(`router/broker.py::handle_frame`/`dispatch`). The Router awaits the reply up to
`request_timeout_s` (default `30s`). Any of {no live link, send failure, `infer_error`,
malformed `response`, link loss, timeout} raises `AgentUnavailable` → the `/v1/message`
caller returns `502 agent_unavailable, retry:true` — **parity with the HTTP-dial path**.
The agent maps an `infer_error` reason from `{unauthorized, unsupported_type,
inference_failed, bad_request}` (the same codes `/infer` would emit), but the Router
collapses *all* of them to `502 agent_unavailable` at `/v1/message`.

#### 3.5.4 Register & heartbeat over the link (slice 2 — "single front door")

In broker mode the agent can **register and heartbeat over the link** instead of POSTing
the Registry directly, so the Router becomes the *only* public endpoint (the Registry needs
no public bind — §3.5.6). After `hello_ok` the agent sends a `register` frame, then
`heartbeat` frames on the `heartbeat_interval_s` cadence (`agent/broker.py`,
`agent/register.py::build_link_registration`). The two frames share an **identical body** —
a heartbeat *is* a `/register` refresh, so `lastSeen`/TTL/stale semantics are unchanged
(feature #54):

```json
{ "type": "register",   "capabilities": ["gpu","llm"], "powerProfile": { … } }
{ "type": "heartbeat",  "capabilities": ["gpu","llm"], "powerProfile": { … } }
```

`RegisterFrame`/`HeartbeatFrame` require only `type`; `advertisedAddress`, `capabilities`,
`powerProfile` are optional; `additionalProperties: false`. **They deliberately carry no
`agentId`.** The Router relays each to the Registry's existing `/register` via the same
`RegistryClient` seam, **binding the registration to the `agentId` the link authenticated
as in its hello** (`router/broker.py::build_relay_body`/`relay_registration`). A
frame-supplied `agentId` is impossible (the contract forbids it) and would be ignored
anyway — register-over-link **cannot impersonate another agent** (bug #54 boundary).

- **`advertisedAddress` is the link, not a dialable host.** Agents **SHOULD omit** it; the
  Router synthesizes the sentinel `broker://<agentId>` (`BROKER_ADDRESS_SCHEME`). It is
  stored on the `AgentRecord` purely so the record has a stable address — placement/pool
  key off `powerProfile`/`capabilities`/`status`, **never the address**, so the sentinel is
  inert, and `/v1/message` always prefers the live link over it.
- **`powerProfile`** passes through verbatim; the Registry validates it against
  `power-profile.schema.yaml` exactly as on the HTTP path (a bad profile → the relay logs a
  `400` and the agent goes stale by TTL).
- The Router acks with `{ "type": "registered" }` — **best-effort**; the agent does not
  block on it. A failed relay is logged and swallowed; the next heartbeat retries, and if
  relays keep failing the agent simply goes `stale` by the normal TTL.
- **No second liveness path.** If the link drops, the agent stops heartbeating and goes
  `stale` via the same TTL — there is no separate link-down liveness signal.

> **Direct mode is unchanged.** With the broker off, the agent POSTs `/register` and runs
> the HTTP heartbeat loop (`agent/register.py::heartbeat_loop`) exactly as in v1. The agent
> picks **exactly one** registration path by config (`agent/main.py`: the direct
> self-register + HTTP heartbeat runs only when `self_register and not broker_enabled`).

#### 3.5.5 Link lifecycle & close codes (RFC 6455)

- **One link per `agentId`.** A newer connection **replaces** the older: the Router drops
  the old link, fails its in-flight dispatches immediately as `AgentUnavailable`, and
  closes the old socket with **`1012`** (`CLOSE_REPLACED`, "replaced by newer connection").
- **`1008`** (`CLOSE_POLICY_VIOLATION`) — bad/malformed `hello` frame, or a `hello` whose
  `authToken` the verifier rejects ("unauthorized").
- **`1003`** (`CLOSE_UNSUPPORTED_DATA`) — a non-JSON first frame, or a non-JSON frame
  mid-stream (the link is dropped).
- A normal disconnect (`WebSocketDisconnect`) just unregisters the link; in-flight
  dispatches on a dropped link fail fast as `502 agent_unavailable, retry:true` rather than
  waiting out the timeout.

#### 3.5.6 LokNet deployment shape (loopback Registry, public Router)

LokNet mode (ADR-0013 follow-up) runs the **Registry on loopback behind the Router**, with
the Router as the only public endpoint:

```
                      outbound wss:// 443 only
  agent (NAT/Cloud Run) ───────────────────────────►  Router (PUBLIC)
    BROKER_ENABLED=true                                   │  relays /register
    SELF_REGISTER=true                                    ▼  over RegistryClient
                                                       Registry (127.0.0.1:8081,
                                                        no public bind needed)
```

Single-instance still applies (in-memory link map + JSON-file registry); a multi-instance
Router needs the v2 Valkey control plane (ADR-0010), out of scope here. The broker's
dispatch seam ("hand work to a link, await a correlated reply") is exactly where that
pub/sub control plane will later sit.

#### 3.5.7 Agent-side link client (reference behavior)

`agent/broker.py::broker_loop` is the agent's side: connect → `hello` → on `hello_ok`,
register-over-link (if `self_register`), then concurrently serve inbound `infer_request`
frames and send `heartbeat` frames. Link failures are **logged and never fatal** — the loop
reconnects with exponential backoff (`broker_backoff_initial_s` doubling up to
`broker_backoff_max_s`, reset after a successful handshake), exiting only on cancellation
(clean shutdown via the app lifespan). `wss://` is required unless `allow_insecure_http` is
set; a custom CA is read from `tls_cert_path` for `wss://` URLs.

---

## 4. Registry API

Base URL (default): `https://127.0.0.1:8081`. Source: `registry/app.py`,
`registry/store.py`. Contract: `contracts/registry.openapi.yaml`. All data endpoints
require a **`Authorization: Bearer <jwt>`** header.

> **Two registration carriers, identical semantics.** An agent reaches `/register` either
> by **POSTing it directly** (direct mode, header bearer) **or by sending `register`/
> `heartbeat` frames over the broker link**, which the Router relays to this same
> `/register` on the agent's behalf (slice 2, §3.5.4). The `lastSeen`/TTL/`stale` semantics
> below are **identical** regardless of which path the registration arrived by — the
> Registry sees an ordinary `/register` call in both cases.

### 4.1 `POST /register`

Register or update (heartbeat) an agent. Auth: header bearer.

**Request body** — `RegistrationBody` (`registry/app.py`; mirrors `AgentRegistration`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `agentId` | string (min 1) | yes | Fleet-unique id. On the relayed path the Router fills this from the link's authenticated identity (never the frame). |
| `address` | string (min 1) | yes | Reachable address, e.g. `10.0.0.5:8444`. **A scheme is optional but recommended** (§8.6 — schemeless is dialed as `https://`). On the relayed path this is the `broker://<agentId>` sentinel. |
| `capabilities` | string[] | no | e.g. `["gpu","llm","tools"]`. |
| `powerProfile` | object | no | Validated against `power-profile.schema.yaml`; persisted for `/pool` and `/schedule`. Invalid profile → `400`. |

Unknown keys are rejected (`extra="forbid"`).

**Response `200`** — an `AgentRecord` (the stored record, read-time annotated):

```json
{
  "agentId": "agent-local",
  "address": "10.0.0.5:8444",
  "capabilities": ["gpu", "llm"],
  "powerProfile": { "name": "gpu-server", "cpus": 16, "memory": "32g", "gpus": "all" },
  "registeredAt": "2026-06-10T13:00:00+00:00",
  "lastSeen": "2026-06-10T13:00:00+00:00",
  "status": "active"
}
```

| Field | Type | Notes |
|---|---|---|
| `registeredAt` | string (date-time) | First registration time; **survives** heartbeat re-registrations. |
| `lastSeen` | string (date-time) | Stamped server-side on **every** successful `/register` (HTTP or relayed). |
| `status` | `"active"` \| `"stale"` | **Computed at read time**, never persisted (§4.7). |

**Errors:** `400 bad_request` (invalid registration or power profile; `detail` carries the
Pydantic message), `401 unauthorized` (bad/missing header token).

### 4.2 `GET /agents`

List all registered agents (header bearer). Returns `200` with an array of `AgentRecord`.
**Includes stale agents** (observability). `401` on auth failure.

### 4.3 `GET /agents/{agentId}`

Look up one agent (header bearer). Returns `200` with the `AgentRecord` (including computed
`lastSeen` + `status`). `404 not_found` for an unknown id; `401` on auth failure.

> This is the exact endpoint the Router calls during **direct-dial** `/v1/message`
> resolution; it reads the `address` field from the `200` body. (Link-first dispatch skips
> it entirely — §3.5.3.)

### 4.4 `GET /pool`

Aggregated stranded-compute capacity across the **live** fleet (header bearer).

**Response `200`** — `PoolCapacity` (`common/power.aggregate_pool`):

```json
{ "nodes": 1, "cpus": 16.0, "memoryBytes": 34359738368, "gpuNodes": 1 }
```

(Single GPU node advertising `cpus: 16`, `memory: "32g"` → `32 × 1024³ = 34359738368`
bytes. With more nodes the fields sum across the live fleet.)

| Field | Type | Notes |
|---|---|---|
| `nodes` | integer | Count of **live** agents that supplied a `powerProfile`. |
| `cpus` | number | Sum of advertised fractional `cpus`. |
| `memoryBytes` | integer | Sum of advertised `memory`, parsed to bytes (`b/k/m/g`, IEC: k=1024). |
| `gpuNodes` | integer | Count of live nodes with a truthy `gpus`. |

Stale agents are **excluded**. Agents without a `powerProfile` do not contribute. Broker-
linked agents appear here normally (their `broker://` sentinel address is irrelevant to the
aggregation). `401` on auth failure.

### 4.5 `GET /schedule?gpu=<bool>`

Capability-aware placement — pick the best-fit **live** node (header bearer).

- Query `gpu` (boolean, default `false`): when `true`, prefer GPU-capable nodes but **fall
  back** to CPU nodes rather than fail ("any accelerator beats none").
- Ranking (`common/placement.select_agent`): GPU-first, then advertised `cpus`, then
  `memoryBytes`, descending. Returns the single best `AgentRecord`.
- **Stale agents are never placement candidates** (`store.list(include_stale=False)`).

**Response `200`:** a single `AgentRecord`. **`404 not_found`** (`detail: "no agents
available"`) when no live agent exists. `401` on auth failure.

### 4.6 `GET /healthz`, `GET /version`, `GET /metrics`

Unauthenticated, same shapes as the Router (§3.2–3.4). `service` metrics label is
`"registry"`. (The Registry has no broker metrics.)

### 4.7 Liveness / TTL semantics (feature #54)

- The agent **heartbeats by re-POSTing `/register`** (direct mode) or **by sending
  `heartbeat` frames** (broker mode) — there is no separate heartbeat endpoint. Each
  successful register refreshes `lastSeen`. Both paths are identical to the Registry.
- A record is `stale` once `now - lastSeen > BARDPRO_AGENT_TTL_S` (`agent_ttl_s`, default
  `45.0s` = 3× the default `heartbeat_interval_s` of `15.0s`, tolerating two missed beats).
- `status` is computed at read time (`store._is_stale` / `_annotated`) and **never
  persisted**.
- **Stale agents stay in `/agents` and `/agents/{id}`** (observability) but are **excluded
  from `/pool` and `/schedule`**.
- A **dropped broker link** is *not* separately detected: the agent stops heartbeating and
  goes `stale` by this same TTL (no second liveness path — §3.5.4).
- Records persisted before liveness shipped (only `registeredAt`, no `lastSeen`) fall back
  to `registeredAt` for the staleness check; a record with neither is treated as stale.

---

## 5. Agent API

Base URL (default): `https://127.0.0.1:8444`. Source: `agent/app.py`, `agent/engine.py`,
`agent/broker.py`. Contract: `contracts/agent.openapi.yaml` (HTTP) +
`contracts/broker-link.schema.json` (link frames). Behind TLS + JWT.

The agent serves inference over **two transports with identical engine semantics**: the
inbound `POST /infer` (below) and, when `BARDPRO_BROKER_ENABLED=true`, inbound
`infer_request` frames on its outbound broker link (§3.5.3). `agent/broker.py::serve_frame`
mirrors the `/infer` handler exactly: same token re-verification, same voice rejection, same
engine, same error envelopes.

### 5.1 `POST /infer`

Process a forwarded `Request` and return a `Response`. This is what the Router calls on the
direct-dial path; it can also be called directly (it re-verifies the token independently).

- **Request body:** a `Request` (same shape as §3.1). Auth: `metadata.authToken` (body),
  not the header (despite `agent.openapi.yaml` declaring `bearerAuth` — §10).
- **Response `200`:** a `Response` (same shape as §3.1). `null` fields omitted.
- **Errors:**
  - `400 bad_request` — body fails schema validation.
  - `401 unauthorized` — `metadata.authToken` invalid/missing/expired.
  - `501 unsupported_type` — `type=voice` (`detail: "voice not supported in MVP"`).
  - `502 inference_failed` with `retry=true` — the engine raised `InferenceError` (e.g. the
    llama.cpp backend is unreachable or returned a malformed completion). `detail` carries
    the cause.

> **Contract note:** `agent.openapi.yaml` documents only `401` and `501` for `/infer`. The
> implementation also returns `400 bad_request` (schema validation) and `502
> inference_failed` (engine error). Both use the standard `Error` envelope; additive
> divergence flagged in §10. On the **broker link**, the agent emits these same four error
> codes inside an `infer_error` frame, which the Router collapses to `502 agent_unavailable`
> at `/v1/message` (§3.5.3).

### 5.2 `GET /healthz`, `GET /version`, `GET /metrics`

Unauthenticated. `service` metrics label is `"agent"`. The agent additionally exposes
`inference_requests_total{backend,outcome}` (`outcome ∈ {ok, error}`,
`make_inference_counter`).

### 5.3 Inference engine backends

Selected by `BARDPRO_INFERENCE_BACKEND` (`inference_backend`, default `echo`) via
`agent/engine.make_engine`:

| Backend | Env value | Behavior |
|---|---|---|
| **EchoEngine** | `echo` (default) | Returns `content = "echo: <input>"` with a demo `toolCalls`/`toolResults` pair (`name="echo"`). Tests/dev path. |
| **LlamaCppEngine** | `llamacpp` | Forwards to a co-located llama.cpp **OpenAI-compatible** server at `BARDPRO_LLAMA_BASE_URL` (default `http://127.0.0.1:8080/v1`), `POST /chat/completions`, `stream=false`. Returns the completion text; no `toolCalls`. |

Any other value raises `ConfigError` at startup. llama.cpp params: `BARDPRO_LLAMA_MODEL`
(default `local-gguf`), `BARDPRO_INFERENCE_MAX_TOKENS` (512), `BARDPRO_INFERENCE_TEMPERATURE`
(0.7), optional `BARDPRO_LLAMA_API_KEY`. (ADR-0003: the agent fronts an OpenAI-compatible
llama.cpp server; multi-backend routing lives at the Router, not in the agent image.) The
broker path uses the **same engine instance** — no backend distinction by transport.

---

## 6. Data types

All wire types are camelCase. Source of truth: `contracts/protocol.schema.json`,
`contracts/power-profile.schema.yaml`, `contracts/registry.openapi.yaml`,
`contracts/broker-link.schema.json`. Pydantic projections: `common/protocol.py`,
`common/power.py`, `registry/app.py`.

### 6.1 `Request`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (UUID) | yes | 8-4-4-4-12. |
| `type` | `"text"` \| `"voice"` | yes | `voice` → 501. |
| `content` | string | yes | UTF-8 text (or base64 audio for voice). |
| `metadata` | `RequestMetadata` | yes | — |

### 6.2 `RequestMetadata`

| Field | Type | Required | Notes |
|---|---|---|---|
| `targetAgent` | string (min 1) | yes | agentId to resolve. |
| `authToken` | string (min 1) | yes | JWT/API key. Validated; MUST NOT be logged. |
| `sessionId` | string | no | Opaque; relayed + echoed. |
| `timestamp` | string (RFC 3339) | no | UTC. |

`additionalProperties: false`.

### 6.3 `Response`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (UUID) | yes | Echoes the request id. |
| `type` | `"text"` \| `"voice"` | yes | — |
| `content` | string | yes | — |
| `metadata` | `ResponseMetadata` | yes | — |

### 6.4 `ResponseMetadata`

| Field | Type | Required | Notes |
|---|---|---|---|
| `agentId` | string (min 1) | yes | Which agent answered. |
| `sessionId` | string | no | Echoed from the request. |
| `timestamp` | string (RFC 3339) | no | — |
| `toolCalls` | `ToolCall[]` | no | Empty/omitted when none. |
| `toolResults` | `ToolResult[]` | no | Empty/omitted when none. |

`additionalProperties: false`.

### 6.5 `ToolCall`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string (min 1) | yes | Tool name. |
| `arguments` | object | yes | Arbitrary JSON object. |

### 6.6 `ToolResult`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string (min 1) | yes | Tool name. |
| `output` | string | yes | Tool output (string). |

### 6.7 `Error` (a.k.a. `ProtocolError`)

| Field | Type | Required | Notes |
|---|---|---|---|
| `error` | string | yes | Machine-readable code (§7). |
| `retry` | boolean | no (default `false`) | Whether retrying may succeed. |
| `detail` | string | no | Human-readable detail. Omitted when null. |

### 6.8 `PowerProfile` (`power-profile.schema.yaml`)

Per-agent resource ceiling; the Router/scripts translate it into podman flags (`--cpus`,
`--memory`, `--pids-limit`, `--gpus`).

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string (min 1) | yes | e.g. `"laptop"`, `"gpu-server"`. |
| `cpus` | number (> 0) | no | Fractional CPUs → `--cpus`. |
| `memory` | string `^[0-9]+(b\|k\|m\|g)?$` | no | e.g. `2g`, `512m` → `--memory`. |
| `pidsLimit` | integer (≥ 1) | no | → `--pids-limit`. |
| `gpus` | string \| null | no | `"all"`, a device id, or `null` → `--gpus`. |
| `batteryAware` | boolean (default `false`) | no | Throttle further on battery. |

`additionalProperties: false`.

### 6.9 `AgentRegistration` / `RegistrationBody` (request)

See §4.1. `required: [agentId, address]`; optional `capabilities`, `powerProfile`.

### 6.10 `AgentRecord` (response)

`AgentRegistration` plus server-stamped `registeredAt`, `lastSeen`, and computed `status`
(§4.1, §4.7).

### 6.11 `PoolCapacity`

See §4.4. `required: [nodes, cpus, memoryBytes, gpuNodes]`.

### 6.12 Broker link frames (`broker-link.schema.json`)

JSON **text frames** on the `/v1/agent-link` WebSocket. All frames are tagged by a `type`
const and forbid unknown keys (`additionalProperties: false`). `Frame` is the
`oneOf` union of the eight below. The frozen `Request`/`Response`/`Error` envelopes are
referenced **by `$ref`** and ride unchanged.

| Frame `type` | Direction | Required fields | Carries | Purpose |
|---|---|---|---|---|
| `hello` | agent → router | `type`, `agentId`, `authToken` | — | First frame after connect; authenticates the link. |
| `hello_ok` | router → agent | `type` | — | Handshake ack; link is live. |
| `infer_request` | router → agent | `type`, `frameId`, `request` | a `Request` | Dispatch work down the link. |
| `infer_response` | agent → router | `type`, `frameId`, `response` | a `Response` | Successful completion for the correlated `frameId`. |
| `infer_error` | agent → router | `type`, `frameId`, `error` | an `Error` | Correlated dispatch failed (mapped to `502 agent_unavailable` at `/v1/message`). |
| `register` | agent → router | `type` | optional `advertisedAddress`/`capabilities`/`powerProfile` | First registration over the link (slice 2). |
| `heartbeat` | agent → router | `type` | optional `advertisedAddress`/`capabilities`/`powerProfile` | Periodic liveness refresh; identical body to `register`. |
| `registered` | router → agent | `type` | — | Best-effort ack that a register/heartbeat was relayed. |

**`FrameId`** — a non-empty string, Router-generated, unique per in-flight dispatch on a
link; the correlation key between `infer_request` and its `infer_response`/`infer_error`.

**`RegistrationBody`** (shared by `register`/`heartbeat`) deliberately carries **no
`agentId`** (the Router binds to the link's authenticated id — §3.5.4). `advertisedAddress`
SHOULD be omitted (Router synthesizes `broker://<agentId>`); `capabilities` forwards
verbatim; `powerProfile` is an opaque passthrough validated by the Registry against
`power-profile.schema.yaml` on relay.

---

## 7. Errors

Every error response carries the same structured envelope (`common/errors.error_response`
→ `ProtocolError`, serialized with `exclude_none`):

```json
{ "error": "<code>", "retry": false, "detail": "<optional human text>" }
```

`retry` defaults to `false`; clients should treat a **missing `retry` as `false`**.
`detail` is omitted when null.

### 7.1 Code → status → retryability

| `error` code | HTTP status | `retry` | Emitted by | Meaning |
|---|---|---|---|---|
| `bad_request` | 400 | false | Router, Agent, Registry | Body failed schema validation, or invalid power profile (Registry). |
| `unauthorized` | 401 | false | Router, Agent, Registry | Missing/invalid/expired/untrusted token. |
| `not_found` | 404 | false | Router, Registry | `targetAgent`/`agentId` unknown, or `/schedule` found no live node. |
| `unsupported_type` | 501 | false | Router, Agent | `type=voice` in the MVP. |
| `agent_unavailable` | 502 | **true** | Router | Registry unreachable, agent unreachable/≥400 (direct dial), **or** broker dispatch failed (missing/dropped link, send failure, `infer_error`, malformed reply, timeout). |
| `inference_failed` | 502 | **true** | Agent | Engine raised `InferenceError` (backend down / malformed completion). |

Only `agent_unavailable` and `inference_failed` are retryable (`retry=true`). The MVP does
not return `429`/rate-limit codes.

**Broker-link errors:** the agent's `infer_error` frame carries an `Error` body with one of
`{unauthorized, unsupported_type, inference_failed, bad_request}` (the same set `/infer`
emits). The Router does **not** surface that inner code to the client — every broker
failure becomes `502 agent_unavailable, retry:true` at `/v1/message`, matching the
direct-dial path.

**Schema enum note:** `protocol.schema.json`'s `Error` description enumerates
`agent_unavailable | unauthorized | unsupported_type | not_found | bad_request` but **not**
`inference_failed`, which the agent emits. Additive divergence (§10).

---

## 8. Worked examples

> These commands are copy-pasteable on macOS/Linux. They use `--insecure`/`-k` because the
> local fleet runs a self-signed dev cert; drop `-k` and trust the CA in production. They
> assume the default ports and a shared `BARDPRO_JWT_SECRET`. The Python one-liners assume
> the project `.venv` (`uv run python ...`).
>
> **Profile A first.** These examples target the **self-hosted / local** path — the home
> power user's MVP. Everything below runs fully on one box with no cloud account (ADR-0014).

### 8.1 Mint a JWT (matches the MVP claim shape)

```bash
export BARDPRO_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

export TOKEN="$(uv run python - <<'PY'
import datetime as dt, os, jwt
now = dt.datetime.now(dt.UTC)
print(jwt.encode(
    {"sub": "demo", "iss": "bardllm-pro",
     "iat": now, "exp": now + dt.timedelta(hours=1)},
    os.environ["BARDPRO_JWT_SECRET"], algorithm="HS256"))
PY
)"
```

The `iss` **must** be `bardllm-pro` (the default `jwt_issuer`) or the verifier rejects it.

### 8.2 Register an agent (Registry, header bearer)

```bash
curl -sk -X POST https://127.0.0.1:8081/register \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
        "agentId": "agent-local",
        "address": "https://127.0.0.1:8444",
        "capabilities": ["gpu", "llm"],
        "powerProfile": {
          "name": "gpu-server",
          "cpus": 16,
          "memory": "32g",
          "pidsLimit": 4096,
          "gpus": "all"
        }
      }'
```

> Give `address` an explicit `https://` scheme. A schemeless `host:port` is accepted and
> the Router will dial it as `https://host:port` (§8.6). In **broker mode** you do not call
> this at all — the agent registers over its link (§8.8).

### 8.3 Send a message through the Router (the product call)

```bash
curl -sk -X POST https://127.0.0.1:8443/v1/message \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
        \"id\": \"11111111-1111-4111-8111-111111111111\",
        \"type\": \"text\",
        \"content\": \"Hello, fleet.\",
        \"metadata\": {
          \"targetAgent\": \"agent-local\",
          \"authToken\": \"${TOKEN}\",
          \"sessionId\": \"sess-1\",
          \"timestamp\": \"2026-06-10T13:00:00Z\"
        }
      }"
```

The `metadata` carries `targetAgent` + `authToken` + `sessionId` + `timestamp`; the
`Authorization` header carries the **same** token (belt-and-suspenders per §2.2). The
Router serves this identically whether `agent-local` is reached over a live broker link or a
direct HTTP dial. With the `echo` backend the response `content` is `"echo: Hello, fleet."`.

### 8.4 Aggregated pool capacity

```bash
curl -sk https://127.0.0.1:8081/pool \
  -H "Authorization: Bearer ${TOKEN}"
# → {"nodes":1,"cpus":16.0,"memoryBytes":34359738368,"gpuNodes":1}
```

### 8.5 Placement (best-fit node, GPU-preferred)

```bash
curl -sk "https://127.0.0.1:8081/schedule?gpu=true" \
  -H "Authorization: Bearer ${TOKEN}"
# → the chosen AgentRecord, or 404 {"error":"not_found","detail":"no agents available"}
```

### 8.6 Agent address & scheme (direct-dial path)

The Router's agent client dials the address from the Registry as-is **if it starts with
`http`**, otherwise it prefixes `https://` (`router/clients.HttpAgentClient.infer`:
`url = address if address.startswith("http") else f"https://{address}"`). So:

- `"10.0.0.5:8444"` → dialed as `https://10.0.0.5:8444/infer`.
- `"http://10.0.0.5:8444"` → dialed as plain HTTP (explicit).
- `"https://10.0.0.5:8444"` → dialed as TLS (recommended explicit form).

A `broker://<agentId>` sentinel address is **never dialed** — it only appears on broker-
linked records, and link-first dispatch reaches the agent down its link.

### 8.7 Health / version / metrics (unauthenticated)

```bash
curl -sk https://127.0.0.1:8443/healthz    # {"status":"ok"}
curl -sk https://127.0.0.1:8443/version    # {"version":"1.3.1"}
curl -sk https://127.0.0.1:8443/metrics    # Prometheus text exposition (incl. broker_* on the Router)
```

### 8.8 Run an agent over the broker link (LokNet, self-hosted Profile A)

No inbound reachability needed — the agent dials *out* to a self-hosted Router:

```bash
# Router (public-ish, but self-hosted on your LAN box): serves /v1/agent-link automatically.
# Registry can stay on loopback behind it (BARDPRO_REGISTRY_HOST=127.0.0.1).

# Agent — opt into the broker; it registers + heartbeats over the link, no /register POST.
export BARDPRO_JWT_SECRET="…"                       # shared fleet secret
export BARDPRO_BROKER_ENABLED=true
export BARDPRO_BROKER_URL="wss://router.lan:8443/v1/agent-link"
export BARDPRO_SELF_REGISTER=true                   # advertise this node over the link
export BARDPRO_CAPABILITIES="gpu,llm"
uv run uvicorn agent.main:app --host 127.0.0.1 --port 8444
```

Then a client `POST /v1/message` to the Router for that `agentId` is dispatched **down the
link** (§3.5.3); the client call is identical to §8.3. To send the link over plain `ws://`
(e.g. only inside an already-encrypted Tailscale/WireGuard hop), you must also set
`BARDPRO_ALLOW_INSECURE_HTTP=true` — otherwise `ws://` fails fast at startup.

---

## 9. Versioning & contract freeze

- **Single source of version truth:** the `VERSION` file at `bardLLMPro/VERSION`
  (currently **`1.3.1`**). `pyproject.toml` reads it via hatchling; `common/version.py`
  resolves it at runtime (preferring the adjacent `VERSION` file, falling back to package
  metadata) so there is never a drifted literal (CLAUDE.md §11).
- **`/version` embeds it:** each service's `GET /version` returns `{"version": "<VERSION>"}`.
  (The OpenAPI summaries promise `vX.Y.Z + sha + date`; the code returns only the version
  string — see §10.)
- **Frozen v1 contracts:** the v1 `contracts/` JSON Schema + OpenAPI files (`protocol`,
  `router`/`registry`/`agent` OpenAPI, `power-profile`) are frozen for v1 (Crawl). They are
  **read-only for service lanes** and **additive-only** — changes are made in `contracts/`
  first and re-propagated, never patched inside a service. The protocol stays
  client-agnostic (ADR-0001).
- **Additive addenda (shipped):**
  - Liveness fields (`lastSeen`, `status`) and the `inference_failed` error code were added
    additively without breaking the frozen envelope.
  - The **LokNet broker** (ADR-0013, `features.md` #59) shipped across v1.1.0–v1.3.x as a
    **new additive contract** — `contracts/broker-link.schema.json` — **not** a mutation of
    the frozen v1 protocol. The frozen `Request`/`Response`/`Error` envelopes ride inside
    the broker frames unchanged, and the v1 HTTP OpenAPI surfaces were left untouched. Slice
    1 (v1.1) added dispatch over the link; slice 2 (v1.2) added register/heartbeat over the
    link ("single front door").

---

## 10. Known gaps & caveats (code vs. contract / external descriptions)

Accuracy over completeness — these are the points where the code, the frozen contracts, and
external descriptions disagree, stated plainly:

1. **`/v1/agent-link` is not in `router.openapi.yaml`.** The broker WebSocket path and its
   frames live **only** in `contracts/broker-link.schema.json` (a separate additive
   contract). The v1 HTTP OpenAPI was frozen and deliberately not modified, so the broker
   endpoint does **not** appear in the Router's OpenAPI document even though it is fully
   implemented and served. (This is by design — ADR-0013 — but worth knowing if you generate
   a client from `router.openapi.yaml` alone.)

2. **`/v1/message` auth carrier.** The contract declares `bearerAuth` (an `Authorization`
   header) and the schema requires `metadata.authToken`. The **Router code verifies the body
   token, not the header.** The Registry endpoints verify the **header**. A correct client
   sends both on `/v1/message`. Real implementation/contract inconsistency.

3. **Agent `/infer` auth carrier.** `agent.openapi.yaml` likewise declares `security:
   [{ bearerAuth: [] }]` (a header) for `/infer`, but the agent reads `metadata.authToken`
   from the **body** (same as the Router). Same body-vs-header split.

4. **`/version` payload.** OpenAPI summaries say `vX.Y.Z + sha + date`; the code returns
   `{"version": "<X.Y.Z>"}` only — no SHA or build date in the response, on any of the three
   services.

5. **Agent `/infer` error coverage.** `agent.openapi.yaml` lists only `401`/`501`; the
   implementation also returns `400 bad_request` and `502 inference_failed` (retryable).
   Additive, but undocumented in the frozen OpenAPI. The broker `infer_error` frame carries
   the same four codes.

6. **`inference_failed` not in the schema enum.** `protocol.schema.json`'s `Error`
   description enumerates `agent_unavailable | unauthorized | unsupported_type | not_found |
   bad_request` but **not** `inference_failed`, which the agent emits. Additive divergence.

7. **Broker `hello` `sub`↔`agentId` binding (open part of bug #54).** The broker handshake
   verifies the `hello` JWT is valid but does **not** cross-check its `sub` claim against the
   claimed `agentId`. The register-over-link relay *is* bound to the hello-authenticated
   `agentId` (so a register frame can't claim a *different* agent's identity — §3.5.4), which
   does not widen the gap, but it does not close it either: a holder of any fleet-valid JWT
   could open a link as an arbitrary `agentId`. This is the still-open boundary of bug #54.

8. **`control-plane.openapi.yaml` is a DRAFT, not part of the v1 API and not the broker.**
   The `contracts/control-plane.openapi.yaml` (Workgroup Control Plane — enroll/workgroups/
   join/approve) is a **DRAFT** for the Profile-B enterprise trust fabric (TRUST_MODEL),
   uses an `identitySig` (hybrid-PQ) security scheme, and has no implementing app in this
   tree. It is **not** the LokNet broker (which *is* shipped — §3.5) and is intentionally
   excluded from the Router/Registry/Agent reference above.

---

## Appendix: source-of-truth map

| Concern | File |
|---|---|
| Wire envelope | `contracts/protocol.schema.json`, `common/protocol.py` |
| Router surface | `contracts/router.openapi.yaml`, `router/app.py`, `router/clients.py` |
| **Broker link contract** | `contracts/broker-link.schema.json` |
| **Broker (router side)** | `router/broker.py`, `router/main.py`, `router/clients.py::RegistryClient.register` |
| **Broker (agent side)** | `agent/broker.py`, `agent/register.py::build_link_registration`, `agent/main.py` |
| Registry surface | `contracts/registry.openapi.yaml`, `registry/app.py`, `registry/store.py` |
| Agent surface | `contracts/agent.openapi.yaml`, `agent/app.py`, `agent/engine.py` |
| Power profile | `contracts/power-profile.schema.yaml`, `common/power.py`, `common/placement.py` |
| Auth | `common/auth.py`, `common/config.py` (`jwt_*`) |
| Self-register / heartbeat | `agent/register.py`, `agent/main.py` |
| Errors | `common/errors.py` |
| Version | `VERSION`, `common/version.py` |
| Metrics / health | `common/metrics.py` (incl. `BrokerMetrics`) |
| Config / ports / broker opt-in | `common/config.py`, `.env.example` |
| Broker / two-profile decisions | `docs/adr/ADR-0013-outbound-agent-broker.md`, `docs/adr/ADR-0014-two-deployment-profiles.md` |
| Maude (example client) | ADR-0011, ADR-0014 |
