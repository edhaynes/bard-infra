# Bard — Security Model & App-Integration Guide

> **Audience.** Security-minded readers (including LSM/SELinux maintainers) and
> client developers integrating against the Bard backend.
>
> **Honesty contract.** Every claim below is marked **[shipped]** (present in the
> v1.3.1 codebase) or **[roadmap]** (designed, not built). Where a feature is
> partially present, the boundary is stated explicitly. This document does not
> describe an aspirational system as if it exists. When in doubt it under-claims.
>
> Verified against: `VERSION` = **1.3.1**; `common/auth.py`, `common/config.py`,
> `router/app.py`, `router/broker.py`, `registry/app.py`, `agent/app.py`,
> `agent/broker.py`, `agent/register.py`, `agent/Containerfile`,
> `agent/Containerfile.cloud`, `router/Containerfile.cloud`,
> `scripts/deploy_loknet_router.sh`, `contracts/protocol.schema.json`,
> `contracts/broker-link.schema.json`; ADR-0004/0013/0014, `TRUST_MODEL.md`,
> `docs/demo/RUNBOOK.md`, root `bugs.md` (#54); and the example client
> `claudeTalk/ios/claudeTalk/Services/{BardProClient,VoiceBackend,KeychainStore}.swift`
> + `claudeTalk/plans/PLAN_appstore_mvp.md`.

---

## 1. Security model overview

**The product is the backend** — the fabric (Router + Registry + agents) and its
frozen API/contracts (ADR-0014). Clients are pluggable consumers of that API.
**Maude (claudeTalk iOS) is the worked *example* client**, not "the" client — it
demonstrates how any app integrates (JWT + `POST /v1/message`). The security
model is therefore a property of the backend and its hops, independent of which
client is talking to it.

### Trust boundary

The trust boundary is the **fabric**: the Router, the Registry, and the agents
that have authenticated into it. Three flows cross it, and **every one carries a
JWT** that is verified at the receiving service:

| Hop | Who → who | Credential | Where verified | **[shipped]** |
|-----|-----------|------------|----------------|---------------|
| Client request | client → Router `POST /v1/message` | JWT in `metadata.authToken` (and, for Maude, also in `Authorization: Bearer`) | `router/app.py` `verify(token)` → 401 on failure | shipped |
| Direct dial | Router → agent `/infer` | the same forwarded token in `metadata.authToken` | `agent/app.py` `verify(request.metadata.authToken)` | shipped |
| Registration | agent → Registry `/register`, `/agents`, `/pool`, `/schedule` | JWT in `Authorization: Bearer` | `registry/app.py` `_bearer(...)` → `verify(...)` → 401 | shipped |
| Broker link | agent → Router `/v1/agent-link` (WebSocket) | JWT in the `hello` frame's `authToken` | `router/broker.py` `handle_agent_link` `verifier.verify(token)` | shipped (opt-in) |

There is **no network-location trust** anywhere in the request path: a packet
"from inside the LAN" earns nothing; the JWT is checked on its own merits at each
service. (Note: this is *authentication of every hop*, not the full zero-trust
*authorization* model of `TRUST_MODEL.md`, which is **[roadmap]** — see §8.)

### TLS-default transport

Transport defaults to TLS. `registry_scheme` defaults to `https`; the broker
`broker_url` must be `wss://`. Cleartext (`http://` / `ws://`) is a **fail-fast,
explicit opt-in** (`allow_insecure_http`) and even then logs a startup WARNING —
see §3 and §4. **[shipped]**

### The swappable verifier seam

Authentication lives **behind an interface** so the credential mechanism can be
replaced without touching call sites:

```python
# common/auth.py
@runtime_checkable
class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict: ...   # claims on success; AuthError otherwise

class JwtVerifier:                              # the one shipped implementation
    def __init__(self, secret, algorithm="HS256", issuer=None): ...
```

Today the only implementation is `JwtVerifier` (HMAC). `TRUST_MODEL.md §10`
plans a PQ-identity verifier that drops into the same seam. **The PQ verifier
does not exist** — only the seam does. **Seam: [shipped]. PQ verifier:
[roadmap].**

---

## 2. The two profiles' security postures (ADR-0014)

The product is **one codebase, two deployment profiles**, selected by config,
which frontend is present, and which trust tier is enabled — never a code fork.

### Profile A — Ad-hoc (home hobbyist) — **the first product MVP**

- **Trust model: implicit.** The user owns every device; there is **no strict
  onboarding, no central authority, no approval gate** (ADR-0014). **[shipped as
  the design point; it is the absence of a gate, so there is nothing to "ship."]**
- **Auth: minimal/default JWT.** A single fleet HMAC secret; any holder of a valid
  token is trusted (see the bug #54 caveat, §6). **[shipped]**
- **Zero mandatory cloud.** The whole fabric runs on a home LAN / self-hosted box
  with no account anywhere. `gcloud` / Cloud Run is **strictly optional and
  redundant** (hard constraint, Eddie 2026-06-10). The LokNet broker, when used,
  points at a **self-hosted** Router — never a required cloud endpoint. **[shipped]**
- **Discovery on a no-cloud LAN** (mDNS/Bonjour vs manual pairing vs self-hosted
  Headscale) is an **open decision** (ADR-0014 Clarify #1). **[roadmap]**

**What Profile A security does provide:** TLS-default transport; every hop
authenticated by a valid fleet JWT; rootless, hardened agent containers (§5).
**What it does not provide:** per-device identity, approval gates, device
revocation, mutual TLS, or any defense against a *holder of the shared secret*
acting as a different agent (§6, bug #54). It is appropriate for a single owner's
own trusted devices, and **not** for a multi-tenant or adversarial-insider
setting.

### Profile B — Managed (enterprise / IT manager)

- **Management console present** (the operator's tool; ADR-0008 split). End-user
  clients still integrate via the same backend API; the console is not an
  end-user app. The console is the maturation of `clients/demo-console`. **Console
  exists today as the demo console; its Profile-B maturation is [roadmap].**
- **Strict device onboarding** — only approved devices join (allowlist + approval
  gate; the `TRUST_MODEL` two-gate device approval, §7 of that doc). **[roadmap]**
- **mTLS + zero-trust identity** (`TRUST_MODEL` v2 software identity → v3 hybrid-PQ
  + MLS). **[roadmap]**
- **MITM authorization — the Router as the single policy-enforcement point.**
  Because every agent **dials in** and every client request **passes through** the
  Router, the Router already sits in the man-in-the-middle position to
  authenticate, authorize, and (optionally) inspect each connection. Profile B
  turns that mediation from pass-through into **enforced policy**.
  - **What is shipped:** the Router *is* the single choke point today — it
    authenticates every `POST /v1/message` and every broker `hello`, and it can
    see request content (it forwards it). The structural MITM position is real and
    present. **[shipped]**
  - **What is roadmap:** policy *enforcement* beyond "valid JWT?" (per-device
    allowlists, role/capability checks, content inspection rules). **[roadmap]**

### Shared core

Same Router / Registry / agent, same contracts, same broker transport. A profile
is **config + frontend presence + trust tier**, not a code fork. The trust fabric
(`TRUST_MODEL` v2/v3) is explicitly **Profile-B scope** and **does not gate
Profile A shipping**.

---

## 3. Authentication & authorization

### The JWT

- **Algorithm:** HS256 (HMAC) by default (`jwt_algorithm`, `common/config.py`).
  Symmetric — there is **one shared fleet secret**, not per-agent asymmetric keys
  (see §6). **[shipped]**
- **Issuer:** default `bardllm-pro` (`jwt_issuer`). When an issuer is configured,
  `JwtVerifier` enforces it (`jwt.decode(..., issuer=...)`). **[shipped]**
- **Expiry:** agents mint **1-hour** tokens (`agent/register.py` `mint_agent_token`:
  `exp = iat + 1h`, `sub = agent_id`, `iss = jwt_issuer`). `JwtVerifier` enforces
  `exp` via PyJWT's default validation. **[shipped]**
- **Where it travels:**
  - Client → Router and Router → agent: `metadata.authToken` (the wire envelope;
    `contracts/protocol.schema.json` marks `metadata.authToken` **required**).
  - Agent → Registry: `Authorization: Bearer <jwt>`.
  - Maude additionally sends the token in **both** `metadata.authToken` *and*
    `Authorization: Bearer` on `POST /v1/message` (`BardProClient.swift`), matching
    the OpenAPI security scheme.
  **[shipped]**

### The `allow_insecure_http` fail-fast gate

`load_config()` validates at startup (`common/config.py` `_validate`):

- `registry_scheme=http` **raises `ConfigError` and refuses to start** unless
  `BARDPRO_ALLOW_INSECURE_HTTP=true` is set explicitly; when opted in, it logs an
  `INSECURE TRANSPORT` WARNING. An unknown scheme is rejected outright.
- `broker_url` starting with `ws://` follows the identical rule
  (`_validate_broker_url`): refuse unless `allow_insecure_http`, else WARNING;
  anything not `wss://`/`ws://` is rejected.

Cleartext is therefore never a silent one-env-var change — it is an explicit,
logged decision, intended only for an already-encrypted hop (e.g.
Tailscale/WireGuard, as the demo uses). **[shipped]**

### Where secrets live (never bundled, never committed)

- **Cloud Router (LokNet):** the JWT secret is injected from **Google Secret
  Manager** at deploy time (`--set-secrets=BARDPRO_JWT_SECRET=...:latest` in
  `scripts/deploy_loknet_router.sh`), **never** `--set-env-vars` and never baked
  into the image. The deploy script will not write the secret value; if the secret
  is absent it fails loudly with the out-of-band creation command. **[shipped]**
- **Maude (iOS):** the fleet JWT lives in the **iOS Keychain**
  (`KeychainStore`, `kSecClassGenericPassword`,
  `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`) under
  `com.edhaynes.claudeTalk.bardpro` / `jwt` — **never** `UserDefaults`, never
  bundled in the app. The user pastes their own token in Settings
  (`PLAN_appstore_mvp.md`). **[shipped]**
- **Agents/Router config:** `jwt_secret` is **required at runtime** and never
  hardcoded; `config.require("jwt_secret")` fails fast if unset. TLS key material
  is referenced by **path only** (`tls_cert_path` / `tls_key_path`) — key bytes
  never live in config. **[shipped]**

> **Authorization, today, is binary:** "is the JWT valid?" There is no per-agent,
> per-role, or per-capability authorization check in the request path yet. Richer
> authorization is the Profile-B / `TRUST_MODEL` roadmap (§2, §8).

---

## 4. Transport security

- **TLS-default** everywhere (§3). HTTPS for client↔Router and Router↔agent;
  `wss://` for the broker link. Cleartext is the gated, logged opt-in. **[shipped]**
- **The LokNet broker — outbound-only, one front door** (ADR-0013). Agents
  optionally hold a **persistent outbound WebSocket** to the Router's
  `/v1/agent-link`. Consequences for the threat surface:
  - **Agents need no inbound ports** — only outbound 443/`wss`. A laptop behind
    NAT, a Cloud Run container, or a homelab box all reach the fabric with nothing
    but an outbound TLS connection. **[shipped, opt-in:**
    `BARDPRO_BROKER_ENABLED=false` by default**]**
  - **The Router is the only public endpoint** in LokNet mode; the Registry binds
    loopback (`127.0.0.1`) behind it and needs no public bind
    (`router/Containerfile.cloud`, ADR-0013 slice 2). **[shipped]**
  - On Cloud Run, **TLS is terminated at the platform edge**; uvicorn speaks plain
    HTTP on `$PORT` *inside* the trust boundary, and the JWT gates every request at
    the app (`--allow-unauthenticated` at the edge is intentional and safe because
    the app, not the platform, authenticates). **[shipped]**
- **Cloud-optional.** Profile A self-hosts the rendezvous (LAN-direct or a
  self-hosted Router); the Cloud Run recipe is *one* option, never load-bearing
  (ADR-0014). **[shipped]**

---

## 5. Container & host hardening

The agent image (`agent/Containerfile`, Red Hat **UBI 9**) and the demo `podman
run` invocations apply baseline hardening. All **[shipped]** unless noted:

- **Rootless Podman**, **non-root user** — the runtime stage drops to `USER bard`;
  only `/opt/bardpro/models` is writable, everything else stays root-owned and
  read-only to the runtime user.
- **`--cap-drop=all`** — all Linux capabilities dropped (demo `podman run` flags).
- **`--security-opt=no-new-privileges`** — no privilege escalation.
- **`--read-only`** root filesystem + **`--tmpfs /tmp`**.
- **`--pids-limit`** (512 in the demo) — fork-bomb containment.
- **No baked ssh host keys** — `ssh-keygen -A` was deliberately removed so
  containers do not share an ssh identity; `openssh-server` is **installed but
  `sshd` is not started in the MVP** (it returns in v2 with the CLI tab, ADR-0004;
  §7). `EXPOSE 8444` only (the agent API).
- The **cloud images** (`agent/Containerfile.cloud`, `router/Containerfile.cloud`)
  mirror the non-root / pip-install shape; they are slim (echo agent / router, no
  llama.cpp, no sshd).

### SELinux — the correct framing

> This section mirrors `docs/demo/RUNBOOK.md` exactly, because it is easy to get
> wrong in both directions.

- **TODAY [shipped]:** on an **SELinux-enforcing host**, the containers inherit
  Podman's **default `container_t` confinement** — **deny-by-default,
  MCS-isolated**. *That is real confinement.* It is not "no SELinux" and it is not
  something we add later; it is the default domain rootless Podman places the
  container in, and it is active on the Linux nodes today.
- **ROADMAP [roadmap]:** **granular, per-workload SELinux policy** (feature **#48**)
  — a tighter custom domain than the default `container_t`. This is *additional*
  hardening on top of confinement we already have, **not** confinement we lack.
- **Scope caveat:** SELinux applies on the **Linux nodes**. The **Mac control
  node has no SELinux** — so this is host confinement on the Linux fleet, **not**
  "default-deny everywhere." Do not over-state it as a fabric-wide property.

---

## 6. Known limitations (honest)

1. **Bug #54 — broker `hello` JWT `sub` is not bound to the claimed `agentId`.**
   In `router/broker.py` `handle_agent_link`, the Router calls
   `verifier.verify(token)` and accepts any **valid** fleet JWT, but it **does not
   check that the token's `sub` claim equals the `agentId` declared in the
   `hello` frame**. Because the MVP uses **one HMAC secret across the whole
   fleet**, any holder of a valid fleet token can open a link claiming *any*
   `agentId` and **intercept that agent's dispatched inferences** — a
   link-hijack vector. **[FIXED v1.5.0 — `hello` now rejects `sub != agentId`
   with close 1008; see `bugs.md` #54. The shared-secret → per-agent-token
   structural fix below remains roadmap.]**
   - **What is *not* affected:** register/heartbeat-over-link is bound to the
     link's already-authenticated `agentId` (`build_relay_body` ignores any
     frame-supplied id; the contract forbids one via `additionalProperties:false`).
     So register-over-link cannot impersonate another agent — but it trusts exactly
     the same `hello` identity, no fresher. This does not widen #54; it also does
     not fix it.
   - **Mitigation plan [roadmap]:** bind `sub`↔`agentId` at `hello`, and/or move
     to **per-agent tokens** (so a leaked token cannot impersonate the fleet),
     tracked on the PLAN_loknet slice follow-ups. The clean structural fix is the
     per-entity identity of `TRUST_MODEL` (§8), which retires the single-shared-
     secret model entirely.

2. **Single shared HMAC secret (MVP).** Authentication is symmetric and
   fleet-wide: one secret authenticates *every* entity. There is no per-entity
   identity, so a single leaked token compromises the trust domain and #54 becomes
   exploitable. Per-entity / asymmetric / PQ identity is **[roadmap]** (§8). The
   `JwtVerifier` is HS256; nothing in the shipped path is asymmetric.

3. **Single-instance link/registry state.** The broker link map is **in-memory in
   the Router process**, and the Registry is a **JSON-file store** — both
   single-instance (ADR-0013, the LokNet deploy pins `--min-instances=1
   --max-instances=1`). A second Router instance would not see the first's links.
   Multi-instance routing waits on the v2 Valkey control plane (ADR-0010).
   **[shipped limitation; multi-instance is [roadmap].]**

4. **No encryption-at-rest yet.** The Registry JSON state, agent volumes, model
   stores, logs, and caches are **not encrypted on disk** today. Encryption-at-
   rest "everywhere," with DEKs wrapped by PQ/hybrid KEKs, is `TRUST_MODEL` goal #9
   — **[roadmap]**.

---

## 7. Connecting apps — integration guide

The backend is the product; this is how anything connects to it.

### 7.1 Generic pattern (any client)

1. **Obtain a JWT.** Sign a token with the fleet's HMAC secret and issuer
   (`iss` = the configured `jwt_issuer`, e.g. `bardllm-pro`; include `exp`). HS256.
   The secret is the fleet's shared secret — held by the operator, never shipped in
   a client.
2. **Point at the Router** (`https://<router-host>:<port>`). The default Router
   port is **8443** (`config.router_port`); the demo runs it on **9443** because
   Tailscale's IPNExtension owns 8443 on the Mac — confirm the actual port for your
   deployment.
3. **`POST /v1/message`** with the protocol envelope:

   ```json
   {
     "id": "<uuid>",
     "type": "text",
     "content": "<the user's message>",
     "metadata": {
       "targetAgent": "<agent-id>",
       "authToken": "<jwt>",
       "sessionId": "<optional>",
       "timestamp": "<optional ISO-8601>"
     }
   }
   ```

   `targetAgent` and `authToken` are **required** by
   `contracts/protocol.schema.json`; `sessionId` and `timestamp` are optional.
   Recommended (matches Maude / the OpenAPI security scheme): also send
   `Authorization: Bearer <jwt>`.
4. **Handle responses.** `200` → a `Response` envelope (`metadata.agentId`,
   `content`). Contract errors: `401 unauthorized`, `404 not_found`,
   `501 unsupported_type` (voice is not supported in the MVP),
   `502 agent_unavailable` (`retry: true`). **[shipped]**

### 7.2 Maude — the example client (claudeTalk iOS)

> Framed explicitly as the **reference example**, not "the" client.

- **Transport:** HTTPS + JWT. `connect(to:)` confirms reachability with
  `GET /healthz` before sending. **[shipped]**
- **On-device STT/TTS.** Speech-to-text and text-to-speech stay on the device
  (Apple Speech / `AVSpeechSynthesizer`); **the only network hop is HTTPS+JWT to a
  Router the user owns** (`PLAN_appstore_mvp.md`). No audio leaves the device.
  **[shipped]**
- **JWT in the iOS Keychain** (`KeychainStore`, §3) — the user's own credential,
  pasted in Settings, never bundled. **[shipped]**
- **`BardProClient.Configuration`:** `targetAgent`, `sessionID`, `token`; the
  router URL arrives via `connect(to:)`. **[shipped]**
- **Real flow:** `send(text:)` builds a `WireRequest` (`type:"text"`, fresh UUID
  `id`, `metadata{targetAgent, sessionId, timestamp, authToken}`), sets
  `Authorization: Bearer <token>`, `POST`s to `<router>/v1/message`, and maps the
  reply — `200` → spoken `answer` envelope; `unauthorized`/`not_found`/
  `agent_unavailable` → spoken `report`; malformed `200` → silent `log`.
  `BardProClient` conforms to the transport-agnostic `VoiceBackend` actor protocol,
  so the app depends only on the abstraction. **[shipped]**

### 7.3 ssh CLI tab (ADR-0004) — **v2 / roadmap**

> **[roadmap — v2 / Walk, Sprint 5.] Not in the MVP.**

The planned in-app terminal is an **ssh client** attaching to an `sshd` inside the
UBI agent (and `openssh-clients` lets a user ssh outbound from the prompt).

- The agent image already **installs** `openssh-server`, configured **key-only (no
  passwords**, `PubkeyAuthentication yes`) — but **`sshd` is not started in the
  MVP**. **[image prep shipped; service off.]**
- A terminal client would authenticate with an **ssh key** (the app holds a key;
  the public key is **mounted at runtime** to `authorized_keys`, never baked into
  the image), and connect over ssh. Client dep `dartssh2` is a **new dependency
  pending license/ARM/maintenance review** (ADR-0004).
- **PQ note [roadmap]:** when the v3 trust layer lands, the ssh transport uses
  OpenSSH PQ KEX (`mlkem768x25519-sha256`); PQ *identity* is app-level ML-DSA, not
  an `ssh-keygen` key.

### 7.4 Agents — how an agent authenticates and joins

An agent presents a self-minted fleet JWT (`mint_agent_token`: `sub=agent_id`,
`iss`, 1-hour `exp`) and joins one of two ways. **[shipped, opt-in.]**

- **Direct `/register`** (default mode): when `BARDPRO_SELF_REGISTER=true`, the
  agent `POST`s `/register` to the Registry with `Authorization: Bearer <jwt>` and
  a body of `{agentId, address, capabilities?, powerProfile?}`. It then
  **heartbeats** by re-POSTing `/register` every `heartbeat_interval_s` (default
  15 s); the Registry stamps `lastSeen` and marks the agent `stale` after
  `agent_ttl_s` (default 45 s = 3 missed beats), excluding stale agents from
  `/pool` and `/schedule` but keeping them in `/agents` for observability
  (feature #54).
- **Register-over-broker-link** (LokNet mode): when `BARDPRO_BROKER_ENABLED=true`
  with `BARDPRO_BROKER_URL=wss://<router>/v1/agent-link` and
  `BARDPRO_SELF_REGISTER=true`, the agent dials the Router's WebSocket, sends a
  `hello{agentId, authToken}` (the Router replies `hello_ok`), then sends
  `register`/`heartbeat` frames the Router relays to the Registry **bound to the
  link's authenticated `agentId`** (the `broker://<agentId>` sentinel replaces a
  dialable address, since the agent is reached down the link). Capability
  advertisement (`capabilities`, `powerProfile`) rides the same frames. The
  heartbeat remains the single liveness authority; a dropped link simply goes
  `stale` by TTL.
- **Security boundary:** see bug #54 (§6) for the `hello`-frame `sub`↔`agentId`
  gap that applies to broker-link join.

### 7.5 Management console (Profile B)

> **[roadmap — Profile-B maturation of `clients/demo-console`.]** The demo console
> exists; its hardening into the Profile-B operator tool is the roadmap.

The console is an **operator** tool (ADR-0008 split), not an end-user app. It
reads `GET /agents`, `GET /pool`, and `GET /schedule` from the Registry and posts
`POST /v1/message` to the Router (`clients/demo-console/src/api.ts`), all
JWT-authenticated (`Authorization: Bearer`). In Profile B this is where MITM
*policy* (device allowlists, role checks) would be administered (§2).

### 7.6 Build-your-own client checklist

- [ ] Obtain a fleet JWT (HS256, correct `iss`, sane `exp`); store it in a
      platform secret store (Keychain / Secret Manager / KMS), **never** bundle it.
- [ ] Default to **HTTPS/`wss`**; only use cleartext over an already-encrypted hop
      and expect the server to refuse `http`/`ws` without the explicit opt-in.
- [ ] `POST /v1/message` with `metadata.targetAgent` + `metadata.authToken`
      (required); add `Authorization: Bearer` to match the OpenAPI scheme.
- [ ] `GET /healthz` to confirm reachability before sending.
- [ ] Handle `401` / `404` / `501` (voice) / `502 retry:true` distinctly.
- [ ] Treat a malformed `200` body as a soft error, not a crash.
- [ ] Do **not** assume per-agent identity or authorization beyond "valid JWT"
      today (§3, §6).

---

## 8. Roadmap of the security model

> Everything in this section is **[roadmap]**. `TRUST_MODEL.md` is `Status: Not
> Implemented — deferred to v3 (Run); direction only`. The accepted decisions
> D1–D5 are **accepted direction for v3, not built**. It is Profile-B scope and
> does **not** gate Profile A.

Tiered, designed-not-done:

- **v2 (Walk).** Software identity + device approval; **Valkey** control plane
  (ADR-0010) to lift the single-instance link/registry constraint (§6.3) and host
  the broker dispatch seam; the broker transport itself (ADR-0013) is **shipped**
  as the v2 transport. **Bug #54 mitigation** (bind `sub`↔`agentId`, per-agent
  tokens) lands here.
- **v3 (Run).** The full `TRUST_MODEL`:
  - **Per-entity hybrid-PQ identity** — `Ed25519 + ML-DSA-65` (FIPS 204) signatures
    (valid only if *both* verify); group key agreement `X25519 + ML-KEM-768` (FIPS
    203 / HPKE RFC 9180). Hybrid, **not** pure-PQ. **The PQ verifier slots into the
    existing `TokenVerifier` seam (§1).**
  - **MLS group keying** (RFC 9420, OpenMLS) — shared per-epoch workgroup key,
    re-keyed on every membership change (forward secrecy + post-compromise
    security); per-sender identity signatures preserve attribution.
  - **Two-gate device approval** — (1) manager/control-plane admission, (2)
    on-device user-presence consent. Optional hardware attestation (Secure Enclave
    / **TPM 2.0, optional**); without it an entity joins at **standard assurance**
    (software keystore) and is policy-gated accordingly.
  - **Encryption-at-rest everywhere** — DEKs wrapped by PQ/hybrid KEKs, never
    co-located with their ciphertext.
  - **Need-to-know at intermediate nodes** — payloads stay end-to-end encrypted;
    relays/bridges see only routing metadata.

### Consistency notes between `TRUST_MODEL.md` and the shipped code

These were checked and are **consistent** — recorded so reviewers don't have to
re-derive them:

- `TRUST_MODEL.md §10` says the trust layer "supersedes the MVP's JWT auth" while
  keeping `metadata.authToken` validation "**behind an interface** so a PQ-identity
  verifier can replace the JWT verifier without touching call sites." This matches
  the shipped `TokenVerifier` Protocol + `JwtVerifier` in `common/auth.py`. The
  seam is real today; only the PQ implementation is deferred.
- `TRUST_MODEL.md` describes a *zero-trust* model with per-entity identity and
  per-action authorization. The shipped fabric is **zero-trust on transport/
  authentication** (no location trust; every hop carries a verified JWT) but is
  **not** the full zero-trust *authorization* model — authorization is "valid JWT?"
  only. This document calls that out throughout (§1, §3, §6) rather than implying
  the `TRUST_MODEL` posture exists.

No contradiction was found between `TRUST_MODEL.md` and the code — the relationship
is "shipped seam, deferred implementation," and the doc and code agree on that.
</content>
</invoke>
