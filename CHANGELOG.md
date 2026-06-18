# Changelog — Bard

All notable changes to the **Bard** subproject (`bardLLMPro/`, incubating)
are documented here. Separate from the consumer app's root `CHANGELOG.md`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Canonical version lives in `bardLLMPro/VERSION`.

## [1.5.6] - 2026-06-12
### Added
- **Sprint B8 — plugin manage (feature #65 complete):** the console Plugins
  pane goes from declared catalog to managed. Contract first:
  `contracts/control-plane.openapi.yaml` gains the plugin surface —
  `GET /plugins` (PluginCatalogView/PluginStatus: the manifest embedded
  verbatim + enable state + reported health),
  `POST /plugins/{pluginId}/enable|disable` (per device OR per workgroup by
  NAME, same derived-WorkgroupId rule as device assignment),
  `GET|PUT /plugins/{pluginId}/config` (per-target config, validated against
  the manifest's OWN configSchema before storing — fail fast, a plugin is
  never enabled with invalid settings), and
  `POST /plugins/{pluginId}/health` (REPORTED health, the agent-heartbeat
  pattern: a report older than the TTL reads "stale"; the control plane
  never probes a plugin over the network). **The frozen plugin-manifest
  contract (the eds-rules book capstone seam) is untouched** — consumed by
  the new surface, never extended. `AuditEntry` extended additively: three
  `plugin-*` actions + optional `pluginId`/`scope` fields.
  Registry: new `registry/plugin_store.py` (JSON persistence, injectable
  clock, per the device_store/audit_log patterns) loads the catalog from
  the example manifests — **Squawk Box + SSH/SCP, the second catalog entry
  proving the seam generalizes** (the actual SSH service stays ROADMAP
  Sprint 5 scope; enablement is desired state in the control plane) — and
  fails fast at startup on a missing/invalid/duplicate manifest. New config:
  `plugin_catalog_dir`, `plugin_state_path`, `plugin_health_ttl_s`; wired
  alongside device identity in `registry/main.py`. `jsonschema` promoted
  from the dev extras to a runtime dependency (manifest + config validation
  now runs in the Registry; MIT, pure Python, ARM-clean). Console: new
  Plugins pane (`src/PluginsPane.tsx`) — catalog cards, on/off toggle per
  device/workgroup target picked from the live fleet, a settings form
  rendered from the manifest's configSchema with plain-language labels (§1;
  raw JSON under a collapsed "Advanced" section), reported health in plain
  words ("Working" / "Not responding"); shared styles extracted to
  `src/styles.ts` (mechanical, §4). Every plugin action lands in the audit
  log and renders on the Activity pane. Playwright structural suite extended
  to 20 tests; new `scripts/smoke_plugin_manage.py` proves the loop on a
  real loopback socket: catalog lists 2 → config-less enable refused (400
  names the missing field) → enable for a workgroup → round-trip through
  GET → config set+get round-trip → health report shows → disable →
  /audit lists the three plugin actions with the actor (8/8 PASS). Pinned
  by `tests/test_plugin_manage.py` (contract-validated).

## [1.5.5] - 2026-06-12
### Added
- **Sprint B6 — management console, manage actions (feature #64 core):**
  the full Tailscale-style manage loop, driven from the console. Contract
  first: `contracts/control-plane.openapi.yaml` gains the console's mutation
  surface — `/devices/{deviceId}/approve|revoke` (served since B2, now
  contracted beside the fleet view), new `/devices/{deviceId}/rename` and
  `/devices/{deviceId}/workgroup` (assign by NAME; the Registry derives the
  `wg_…` WorkgroupId deterministically from it per trust.schema — null
  clears), and `GET /audit` (`AuditView`/`AuditEntry`).
  `contracts/enrollment.schema.json` extended additively: optional
  `DeviceRecord.workgroup`. Registry: `DeviceStore.rename` /
  `assign_workgroup` persist on the device record; `registry/fleet.py` now
  surfaces the assigned workgroup through `GET /fleet` (the B5 always-null
  field, closed); new `registry/audit_log.py` — append-only JSONL audit of
  every management action (who = manager token `sub`, what, which device,
  when; injectable clock), wired via new `audit_log_path` config alongside
  device identity. Console: the `src/api.ts` seam grows the typed mutations
  + audit read; device rows get plain-language actions ("Approve",
  "Rename", "Group", "Remove device" with confirm), the one-time device
  code is surfaced in a dismissible panel at approval, and a read-only
  "Activity" pane renders the audit trail. Playwright structural suite
  extended to 13 tests (mocked API: clicking fires the right request with
  the bearer, UI reflects the mocked state change, audit entries render).
  New `scripts/smoke_console_manage.py` proves the loop on real loopback
  sockets: enroll → pending in /fleet → console approve (one-time secret) →
  device serves over its outbound broker link through the Router → rename +
  workgroup reflected in /fleet → console revoke → the same device token is
  rejected → /audit lists all four actions with the actor. Pinned by
  `tests/test_console_manage.py` (contract-validated).
- **Sprint B5 — management console, read-only (feature #64 first slice):**
  `GET /fleet` added to `contracts/control-plane.openapi.yaml` (FleetView /
  FleetDevice: enrollment state × heartbeat-derived connection × power-profile
  capabilities × nullable workgroup) and served by the Registry
  (`registry/fleet.py` pure join + one additive route). `clients/console/`
  now renders the real fleet from the API — plain-language device rows
  (Online / Not responding / Offline, "Last seen"), workgroup grouping per
  trust.schema, env-driven API base URL with loud failure (sample data only
  behind an explicit `VITE_USE_SAMPLE_DATA=true`). Read-only by design;
  mutations are Sprint B6 (seam: `clients/console/src/api.ts`). Playwright
  structural test suite (7 tests, mocked API; `@playwright/test` 1.60.0,
  Apache-2.0, pinned exact).

## [1.5.4] - 2026-06-12
### Security
- **B4 — relay auth on per-device identity (bug #56 fabric side / audit C-1
  downgraded, H-2 mitigated).** With `BARDPRO_DEVICE_IDENTITY_ENABLED=true` the
  Router's data path — `POST /v1/message` and the broker `/v1/agent-link`
  hello — now verifies per-device credentials: new
  `common.device_auth.FleetOrDeviceVerifier` tries the fleet JWT first (legacy
  agents keep working, opt-in coexistence — no flag-day) and otherwise requires
  a per-device token that `PerDeviceVerifier` resolves against the device
  store, so unauthenticated, unknown, pending, revoked, and cross-device (A's
  key claiming sub=B) relays are rejected before anything is dispatched. New
  `DeviceStore(reload_on_read=True)` re-reads the JSON store at each key
  lookup, so a Registry-side revoke takes effect at the Router on the next
  request without a restart. Router entrypoint wires this from config; the
  fleet-JWT-only path is byte-for-byte unchanged when the flag is off.
  Pinned by `tests/test_security_pentest.py` §7 (unauthenticated /
  revoked-device / cross-device relay rejected; active-device and fleet-JWT
  controls relay; broker link accepts a device credential and rejects it after
  revoke) and new `tests/test_device_identity.py` B4 sections.
  `docs/SECURITY_AUDIT.md` C-1/H-2 updated — the Maude/claudeTalk voice-WS
  client adoption of per-device tokens remains open in bug #56 (other
  codebase); the public-exposure launch gate stands.

## [1.5.3] - 2026-06-12
### Added
- **B3 channel invites — one-click link/QR redemption, no account** (features #67/#81,
  the "send a link, click, you're in" flow). New FROZEN contract
  `contracts/invite.schema.json`: an owner/manager mints a shareable, single-use,
  expiring channel invite (`POST /invites`, manager-authed → invite record + token +
  ready-to-send URL with the token as the `invite` query param; QR rendering is
  client-side — the URL is the QR payload, no new dependency). A worker redeems it
  (`POST /invites/{token}/redeem`, deliberately NOT bearer-gated — the link IS the
  authorization) and the device is admitted **ACTIVE into the channel in one step**,
  receiving its per-device HMAC secret (one-time disclosure, same rule as approve).
  Deliberately distinct from fleet enrollment, which still requires manager approve.
  New `registry/channel_store.py` (`ChannelStore`: invite JWTs aud
  `bard-channel-invite` signed by their OWN key, single-use jti burn, expiry on the
  injected clock, JSON persistence in its own file, channel→devices membership +
  `GET /channels/{id}/members`), `DeviceStore.admit` (direct-to-active admission;
  rejects an existing deviceId so a redeem can't take over an enrolled device — and
  a failed admission does NOT consume the invite). Config: `BARDPRO_CHANNEL_INVITE_SECRET`
  (required ≥32 bytes when device identity is on), `BARDPRO_CHANNEL_INVITE_TTL_S`
  (default 7 days), `BARDPRO_INVITE_BASE_URL` (required) — fail-fast validated.
  The mobile redemption UI (open link → channel appears → hands-free PTT) is out of
  backend scope — lands in the Maude/claudeTalk app (#67/#81).
- **B2 per-device identity (note)**: the enrollment lifecycle (ADR-0010 — join-token
  → pending → approve → active → revoked, `contracts/enrollment.schema.json` FROZEN,
  `DeviceStore`, `PerDeviceVerifier`, Registry `/enroll` + `/devices*`, opt-in
  `BARDPRO_DEVICE_IDENTITY_ENABLED`) landed after 1.5.2 without a version bump
  (commit ef5435c); it ships in this release.

## [1.5.2] - 2026-06-11
### Added (docs only)
- **ADR-0015 — free for adoption, paid only for opex**: client $0 (no IAP/unlock),
  platform + plugins free; only paid product = at-cost subscription covering the opex
  ledger (hosted Hub, gcloud broker instances, weekly UBI rebuilds #69, Apple dev sub).
  Weighed-and-rejected alternatives documented (paid plugins as profit lever, $0.99
  client unlock, paid client / free infra).
- **features.md #72–#78** (2026-06-11 distribution review): coding-agent plugin —
  Claude Code as a fleet agent, Happy-architecture research folded in (reuse
  `happy-cli src/claude` pattern, skip happy-server, ACP compatibility = distribution
  channel); iOS-gateway-to-desktop-OSS platform thesis; Flutter Windows client test on
  frogstation; "Linux terminal in your pocket" audience segment; monetization weighing
  (resolved → ADR-0015, **Hub $19.99/yr**); white-label/skinnable client for
  businesses (server-pushed branding, one binary); Siri/HomeKit bridge rungs (HA
  HomeKit path, macOS `shortcuts run`, App Intents, acoustic-demo gag).
### Changed (docs only)
- **POSITIONING.md** business model refined per ADR-0015: pro unlock dropped; opex
  line items enumerated; Hub launch price **$19.99/yr** (break-even ≈ 25 subs, $0 ad
  budget, price revisited downward as the base amortizes fixed opex).
### Security
- **Minimum JWT secret length enforced — 32 bytes** (bug #58, found by the live pentest 2026-06-10). `common/config.py` `Config.require` now rejects a present-but-too-short `BARDPRO_JWT_SECRET` (`len < MIN_JWT_SECRET_BYTES` = 32) with a `ConfigError` naming the var and the RFC 7518 §3.2 / HMAC-SHA256 minimum, so a brute-forceable shared secret fails fast at startup (both `load_config` and `JwtVerifier.from_config` paths). Previously only presence was checked. Keyed to `jwt_secret` so `require` stays generic for other keys.
### Added
- **`tests/test_security_pentest.py` — adversarial pentest as a CI security-regression suite.** Boots the real Router/Registry/Agent stack via `TestClient` and asserts ~23 attacks stay **defended**: no-auth → 401 on router `/v1/message`, registry `/register`/`/agents`/`/pool`/`/schedule`, agent `/infer`; forged tokens rejected (garbage, wrong-secret, `alg:none`, no-exp, no-sub, no-iss, expired, wrong-issuer); Pydantic extra-field injection → 400; malformed JSON → not 500; M-4 (router authenticates the body token, a valid header alone does not grant access); the #54 broker hijack (`sub != agentId` → WS 1008, link not registered) plus the `sub == agentId` control and a forged-token broker link. Any regression of the auth/#54 fixes now fails CI.

## [1.5.0] - 2026-06-10
### Security
- **Broker `hello` binds JWT `sub` ↔ claimed `agentId`** (bug #54 / audit finding H-1). `router/broker.py` `handle_agent_link` now captures the verified token claims and rejects the link (WebSocket close 1008, link **not** registered) when `claims["sub"] != agentId`. Closes the link-hijack vector where, under the single shared-fleet-secret model, any valid token could claim any `agentId` and intercept that agent's dispatched inferences.
- **`JwtVerifier.verify` now requires `exp`/`iss`/`sub` and validates expiry** (audit finding M-1). `common/auth.py` passes `options={"require": ["exp", "iss", "sub"], "verify_exp": True}` (plus 30s `leeway` for clock skew) to `jwt.decode`. Previously a token minted with no `exp` would never expire. All existing minters (`agent/register.py`, the test JWT helper, smoke/demo scripts) already set these claims — no minter changes required.

## [1.4.2] - 2026-06-10
### Added (docs)
- **`docs/SECURITY_AUDIT.md`** — independent read-only security evaluation: fabric sound + honestly-documented for Profile A; 1 Critical (Maude relay no-auth/plaintext — E2EE paper-only, launch-gate), 3 High (bug #54 link-hijack confirmed; single shared HMAC secret; E2EE unimplemented), 7 Medium, severity-ranked findings + prioritized launch-gate fix list + a 3-gate external-audit scope. bugs #55 (JWT require-claims), #56 (relay auth gate), #57 (rotate ElevenLabs key) filed; #54/#55 code fix in flight (v1.5.0).

## [1.4.1] - 2026-06-10
### Added (docs)
- **`docs/MARKETING_SCAN.md`** (Linda scan + Jason synthesis): taglines, channels (homelab beachhead), launch order, steal-from-competitors, do/don't, and the **LokNet rename** recommendation (now multi-source). features #68 plugin catalog +SSH/SCP plugin (i).


## [1.4.0] - 2026-06-10
### Added (vision / strategy — docs only)
- **`VISION.md`** (repo root) — the single consolidating map: founding principle ("take computing back to the 80s — you own your stuff"), the convergence thesis, the products (Bard LLM / Bard / LokNet Hub / Maude), business model, two profiles, and a **near-term-shippable vs platform-horizon roadmap** ("what to build Monday"). Pointers to POSITIONING/ADRs/plans/features.
- **Open-weight-first strategy** (POSITIONING + #7): the curated core is open-*weight* models you can own; permissive-licensed preferred for mirrorability (#70); closed/API opt-in only.
- **feature #71 — Trust & Safety / lawful-use + jurisdiction framework**: layered abuse handling (AI content guardable via prompt/output guards; E2EE comms handled at account/report/legal layer, no backdoors), acute risks (image-gen plugin, hosted E2EE tier), EU read (GDPR asset, AI Act transparency, Chat Control watch-item) — legal counsel gates hosted/image-gen/EU launch.


## [1.3.4] - 2026-06-10
### Added (positioning — docs only)
- **Founding principle of Bard Software** (`docs/POSITIONING.md`): **"take computing back to the 80s — you own your stuff."** Everything is downstream: privacy+access, free self-host / one-time own-it, *not a profit center* (adoption over extraction; subs cover real cost, never extract), convergence + LokNet Hub + plugins as the means. Pricing principle refined: free/one-time for what costs us nothing ongoing & isn't update-dependent (you own it); subscription for hosted resources and update-dependent things — the concrete driver being weekly UBI CVE rebuilds (#69).
- **feature #69**: automated weekly UBI rebuild → Clair → cosign → Quay pipeline (the security-currency cost behind update-dependent pricing).


## [1.3.3] - 2026-06-10
### Added (positioning / product direction — docs only)
- **`docs/POSITIONING.md` crystallized** (Eddie session 2026-06-10): identity = **"Connect your stuff, in your network"** (the *convergence* of your people + AI + compute is the differentiator; LokNet demoted to plumbing, "VPN" dropped as the lead). Named the rendezvous the **LokNet Hub**. Business model **confirmed**: free Maude app + upsell (hosted LokNet Hub subscription + optional pro unlock); monetize access/convenience, not privacy. The Hub is a **plugin platform** (Home-Assistant model; #66). Onboarding ladder (hosted Hub default → self-host upgrade), with E2EE as the license-to-charge gate.
- **features #65–#67**: hosted LokNet Hub subscription (#65), Hub plugin platform/SDK (#66), Valkey caching/ephemeral-state/pub-sub layer (#67); **#60** refined to integrate mature NAS (Synology) now + device-pooled distributed storage as a future lift.


## [1.3.2] - 2026-06-10
### Added
- **`docs/API_REFERENCE.md`** — thorough, code-verified reference for the backend API (the product surface per ADR-0014): Router (incl. the LokNet `/v1/agent-link` broker WS + full frame protocol), Registry (incl. register-over-link + liveness/TTL), Agent, every wire data type, the error envelope, worked curl examples, and a known-gaps section (OpenAPI-vs-broker-schema gap, `/v1/message` body-token-vs-header split, `/version` shape, bug #54 boundary). Framed for Profile A (home power user) first; Maude referenced as the example client.
- **`docs/SECURITY_AND_INTEGRATION.md`** — security model + app-integration guide. Per-hop JWT, TLS-default, LokNet outbound-only transport, the two-profile postures (ADR-0014), container/host hardening with the correct default-`container_t` SELinux framing, honest known-limitations (bug #54, single shared HMAC secret, single-instance state, no encryption-at-rest), and the connect-your-app guide (generic pattern, Maude example, ssh tab v2, agents, console). Shipped-vs-roadmap tagged throughout.

## [1.3.1] - 2026-06-10
### Added
- **ADR-0014: two deployment profiles.** Profile A (home hobbyist — ad-hoc, no management console, zero mandatory cloud) is the **first product MVP**; Profile B (enterprise — management console, strict device onboarding, MITM authorization via the Router as policy-enforcement-point) follows. The **product is the backend API/contracts**; Maude is the **example** client (refines ADR-0011). Standing constraint: cloud (Cloud Run) is always optional/redundant, never load-bearing — reframes the LokNet slice-3 recipe as one rendezvous option among self-hostable equivalents. Resolves the console question: the console is Profile-B-only.

## [1.3.0] - 2026-06-10
### Added
- **LokNet Cloud Run deploy recipe — public Router, scale-pinned (feature #59 / ADR-0013, slice 3). Authored, not executed: the public deploy is Eddie's to run; no `gcloud`/`podman push` was invoked.**
  - **`router/Containerfile.cloud`** — the public Router image. Mirrors the scale-to-zero echo node's UBI9 / non-root / `pip install .` shape (`agent/Containerfile.cloud`); runs `uvicorn router.main:app` on `$PORT` with **TLS terminated by Cloud Run** (uvicorn speaks plain HTTP behind the managed edge). Defaults `BARDPRO_REGISTRY_HOST=127.0.0.1` (the Registry stays private/loopback behind the Router — single front door). The JWT secret is injected at runtime, never baked in.
  - **`scripts/deploy_loknet_router.sh`** — idempotent, parameterized (`PROJECT` required and never hardcoded; `REGION`/`SERVICE`/`REPO`/`IMAGE_TAG`/`SECRET_NAME`/`BUILDER` overridable). Ensures the Artifact Registry repo (`describe || create`) and verifies the Secret Manager secret exists (failing loudly with the create command — it never handles the secret value). Builds + pushes via podman/docker or Cloud Build, then `gcloud run deploy` with **`--min-instances=1 --max-instances=1`** (in-memory link map + in-process Registry → single instance until the v2 Valkey control plane, ADR-0010; explained in a comment), **`--set-secrets=BARDPRO_JWT_SECRET=...`** (not plain env — mirrors the cloud node), **`--allow-unauthenticated`** (JWT gates at the app), `--timeout=3600` (the 60-min WebSocket cap), and honors `$PORT`. Every multi-flag command is wrapped with trailing backslashes (CLAUDE.md §14). Validated with `bash -n` and `shellcheck` (clean); the script itself was **not** run.
  - **`docs/demo/LOKNET_CLOUDRUN.md`** — the runbook: agents dial out 443-only (no Tailscale, no inbound), the deploy steps, **why the 60-min Cloud Run WebSocket cap is survivable** (the slice-1 reconnect loop re-establishes the link and re-registers; heartbeat TTL covers the gap), the single-instance constraint, Registry-reachability options, and how to point a remote agent at the public Router (`BARDPRO_BROKER_URL=wss://<router>/v1/agent-link`, `BARDPRO_BROKER_ENABLED=true`, `BARDPRO_SELF_REGISTER=true`). Explicitly states **the Chris demo is NOT rewired to this — it stays on the verified Tailscale path** (PLAN_loknet decision 3).
- **No new dependencies.** No library code changed (deploy artifacts + docs only); the 100% line+branch test gate is unaffected.

## [1.2.1] - 2026-06-10
### Added
- **Real-socket mesh-free broker smoke (`scripts/smoke_broker.py`) — the Tailscale-free proof both prior slices flagged as a gap.** Stands up the full LokNet topology on real localhost TLS/WSS sockets (not the in-process `TestClient`): a **private, loopback** Registry, a public-facing Router (the single front door), and **one** agent in broker mode (`BARDPRO_BROKER_ENABLED=true`). The agent is deliberately given **no usable direct route to the Registry** — its `registry_host:registry_port` point at a freshly-closed loopback port — so a direct `/register` dial would be refused. The smoke then asserts the agent registered **purely over the outbound link** (`broker://<agentId>` sentinel in `/agents`), `/pool` aggregates its power profile (`nodes >= 1`), `/schedule` picks it, and a `POST /v1/message` to the Router returns a real echo completion dispatched **down the link**. Prints `BROKER SMOKE: PASS` and exits 0/1. Modeled on `scripts/smoke_local.py`; reuses the `trustme` throwaway-CA pattern; needs no network beyond loopback.
- **CI: the broker smoke runs as a step in `bardpro-ci.yml`** (after the test step, both OSes), so the real-socket mesh-free path is exercised on every push/PR.
### Changed
- **CI lint gate tightened to a full `uv run ruff check .`** (the E501 `--ignore` was removed): the 15 pre-existing long lines were wrapped at the laughing-bell tip, so the repo is at zero lint debt and the full check is now the blocking gate.
### Notes
- **No real bug surfaced under real sockets vs `TestClient`.** The slice-1/2 broker code behaved exactly as designed end-to-end. Two log lines are benign-by-design and intentionally left as-is: the agent logging the Router's best-effort `{"type":"registered"}` ack as an "ignoring unexpected frame" (its serve loop only handles `infer_request`), and a single `broker link down, reconnecting` emitted during test teardown when uvicorn closes the live WebSocket (1012) on shutdown — the slice-1 reconnect loop correctly backing off. No library change was needed; 100% line+branch coverage holds.

## [1.2.0] - 2026-06-10
### Added
- **LokNet slice 2 — single front door: registration + heartbeat ride the broker link (feature #59 / ADR-0013 follow-up).** Fully additive, default off; direct mode (no broker link) is completely unchanged — agents still POST `/register` to the Registry directly. In broker mode the Router becomes the only public endpoint and the Registry needs no public bind.
  - **Contract (additive, frozen v1 schemas untouched):** `contracts/broker-link.schema.json` gains `register` / `heartbeat` (agent→router, identical body: optional `advertisedAddress` / `capabilities` / `powerProfile`, deliberately **no** `agentId`) and `registered` (router→agent, best-effort ack). A heartbeat frame IS a `/register` refresh — same `lastSeen`/TTL/stale semantics as feature #54.
  - **Agent:** with `BARDPRO_BROKER_ENABLED=true` the agent registers and heartbeats **over the link** and the direct HTTP `/register` + heartbeat loop is suppressed (one registration path, chosen by config in `agent/main.py`). After `hello_ok` it sends a `register` frame, then `heartbeat` frames every `heartbeat_interval_s`, concurrently with serving inbound infer frames on the same socket (`agent/broker.py`; `build_link_registration` in `agent/register.py`). Injected `heartbeat_sleep` keeps it test-deterministic.
  - **Router:** register/heartbeat frames from a link are relayed to the Registry's existing `/register` via the same `RegistryClient` seam used for lookups (new `register` method; `HttpRegistryClient` + protocol). The relay is **bound to the `agentId` the link authenticated as in its `hello`** — any `agentId` in the frame is ignored (`router/broker.build_relay_body`), so register-over-link cannot impersonate another agent (does not fix bug #54, does not widen it). Registry failures are logged and swallowed; the link stays up and the next heartbeat retries.
  - **advertisedAddress sentinel `broker://<agentId>`:** in broker mode the Router reaches the agent down the link, not by dialing an address, so the agent omits the address and the Router synthesizes the sentinel. Placement/pool key off `powerProfile`/`capabilities`/`status`, never the address; `/v1/message` always prefers the live link.
  - **Liveness:** a dropped link is not separately detected — the agent simply stops heartbeating and goes `stale` by the normal TTL (no second liveness path; verified by test).
  - **Deployment shape (ADR-0013 follow-up note):** Registry on loopback (`BARDPRO_REGISTRY_HOST=127.0.0.1`), Router public; nothing forces a public Registry bind.
  - **No new dependencies.** Tests: 228 total (was 208) at the enforced 100% line+branch gate — register/heartbeat relay bound to link identity, forged-agentId ignored, `lastSeen` refresh + pool/schedule visibility (real store + injected clock), dropped-link→stale-via-TTL, agent-side over-link register/heartbeat session (injected connector/sleep, no sockets), broker mode does not hit HTTP `/register`, direct mode still POSTs.

## [1.1.0] - 2026-06-10
### Added
- **Outbound-agent broker link (feature #59 / ADR-0013) — first v2 (Walk) feature; Tailscale no longer required for reachability.** Fully additive; direct dial stays the default.
  - **Router:** new WebSocket endpoint `/v1/agent-link` — an agent connects outbound, authenticates a `hello` frame with its JWT (same `TokenVerifier` seam), and the Router keeps an in-memory link registry (`router/broker.py`, one link per `agentId`; a newer connection replaces the older, close 1012). `/v1/message` for a target with a live link dispatches a `frameId`-correlated `infer_request` down the socket and awaits the reply (deadline = `request_timeout_s`; timeout / link loss / agent-reported error / send failure all map to `502 agent_unavailable retry:true`, parity with the dial path). No live link → the v1 registry-lookup + HTTP-dial path, unchanged (now run off the event loop via `asyncio.to_thread`).
  - **Agent:** opt-in via `BARDPRO_BROKER_ENABLED` (default **false**) + `BARDPRO_BROKER_URL` (wss:// required; ws:// only with the existing `ALLOW_INSECURE_HTTP` opt-in, mirroring the registry-scheme gate). A background task (`agent/broker.py`) connects, authenticates with the same self-minted JWT `/register` uses, and serves inbound frames through the **same `InferenceEngine`** and the same auth/voice/error semantics as HTTP `/infer`; exponential reconnect backoff (`BROKER_BACKOFF_INITIAL_S`→`_MAX_S`, reset after a good handshake), clean cancel on shutdown. The `/register` heartbeat (feature #54) is untouched and remains the liveness authority.
  - **Contract (additive):** `contracts/broker-link.schema.json` — hello / hello_ok / infer_request / infer_response / infer_error envelopes wrapping the frozen `protocol.schema.json` shapes; v1 OpenAPI files unmodified. Contract tests validate fixtures **and** the agent's real served frames against the schema.
  - **Observability:** JSON-logged link up/down/dispatch events; router gauge `broker_link_active{agentId}` + counter `broker_dispatch_total{agentId,outcome}` (`BrokerMetrics`, same per-app-registry pattern as the inference counter). Note: broker-served inferences do not increment the agent's `inference_requests_total` (HTTP-path counter) yet.
  - **No new dependencies:** server WS is starlette in-tree; the agent client uses `websockets` 16.0, already pinned via `uvicorn[standard]` in `uv.lock`.
  - Tests: 208 total (was 160) at the enforced 100% line+branch gate — connection manager (register/replace/disconnect/correlation), dispatch-with-link vs fallback, timeout→502, WS auth-reject, agent loop with fake connections + injected sleep (no sockets, no waiting), config gates, contract parity.

## [1.0.1] - 2026-06-10
### Added
- **ADR-0013: outbound-agent broker transport (WebSocket).** First v2 (Walk) decision, scoping root features.md #59: agents optionally hold a persistent outbound WS to the Router's `/v1/agent-link`; the Router dispatches `/infer` work down that link when present and falls back to the existing direct HTTP dial otherwise (fully additive, default unchanged). Every node then needs only outbound 443 to one public TLS endpoint — no mesh/port-forwarding/Tailscale — and the Cloud-Run registration-by-proxy hack dies. WS chosen over SSE (need bidirectional) and gRPC (zero new deps: `uvicorn[standard]` already pins `websockets` 16.0 in `uv.lock`). Numbered 0013 because ADR-0012 (console frontend stack) already exists — the feature brief said 0012 before that landed.

## [1.0.0] - 2026-06-10
### Released — v1 "Crawl" MVP complete
- All MVP gates green from a clean checkout: 160 tests at 100% line+branch coverage, TLS-default fleet smoke PASS (no insecure opt-in), CI live (lint/test matrix + gitleaks + multi-arch agent image), README regenerated.
- Scope as shipped: Router + Registry (JSON store, heartbeat liveness, `/pool`, `/schedule`) + UBI-9 Podman agent (llama.cpp or echo behind `InferenceEngine`), JWT auth behind a swappable verifier, Prometheus `/metrics` + JSON logs, frozen contracts. v1 client = Maude (claudeTalk v0.1.0+, ADR-0011).
- Out of scope per ROADMAP: mesh, voice payloads, console, remote spawn, ssh tab, trust fabric (v2/v3). Next up: outbound-agent broker (features #59) to drop the Tailscale dependency.

## [0.13.2] - 2026-06-10
### Changed
- **README regenerated from scratch** (repo rule §8, Sprint 4). Now reflects the post-ADR-0011 reality: Maude (claudeTalk iOS) as the v1 client, Flutter parked for v2; S1/S3 verified, S4 in progress. Full §8 order — what/who-for, quick start (macOS/Linux/Windows), a complete configuration table covering **every** `common/config.py` field (30 vars incl. heartbeat/TTL, log-format, allow-insecure-http) plus the script-level `BARDPRO_*` helpers, tests (160, 100% line+branch gate), per-component architecture (contracts/common/router/registry/agent/trust stubs/clients incl. demo console), deployment (local uv, Podman/UBI with default-deny notes, Cloud Run scale-to-zero, demo_up.sh), and a troubleshooting table of real shipped issues (#51 libcurl-minimal `--allowerasing`, #53 insecure-http gate, Tailscale-owns-8443 → router :9443, model-fetch fail-fast, JWT_SECRET fail-fast, 401/404/502 triage). Every claim checked against the code — corrected along the way: `/version` returns the VERSION-file version (no sha/date), placement is best-fit GPU→CPU→memory in `common/placement.py`, and default-deny podman flags live in the demo scripts (run_agent.sh does resource limits).

## [0.13.1] - 2026-06-10
### Changed
- **S3 remainder closed: TLS-default fleet verified (no code change).** `uv run python scripts/smoke_local.py` run with `BARDPRO_ALLOW_INSECURE_HTTP` explicitly **unset**: all three services (registry :8081, agent :8444, router :8443) come up as real uvicorn **HTTPS** servers on throwaway trustme certs, agent registers (200, with the v0.11.0 liveness fields `lastSeen`/`status: active`), and a JWT-authed text message flows Router→Agent→echo end-to-end (200, `echo: …`). `SMOKE: PASS`, exit 0 — verbatim output in the commit body. No script updates needed after the liveness/metrics/tightening changes. `PROJECT_PLAN.md` sprint table updated: S3 ✅ (remainder verified), S4 🔄 in progress (CI shipped in 0.13.0).

## [0.13.0] - 2026-06-10
### Added
- **GitHub Actions CI pipeline (Sprint 4).** New live workflow `.github/workflows/bardpro-ci.yml`, path-filtered to `bardLLMPro/**` so iOS-app changes never trigger it (monorepo). Jobs: (a) `lint-and-test` on **ubuntu-latest + macos-latest** — `uv sync --all-extras`, blocking `ruff check --ignore E501` (15 pre-existing E501s tracked as debt; full ruff runs as a non-blocking report), and `uv run pytest`, whose pyproject `--cov-fail-under=100` line+branch gate IS the CI gate; (b) `secret-scan` — `gitleaks/gitleaks-action@v2` over full history (personal-account repo, no license key needed); (c) agent-image builds of `agent/Containerfile` via docker buildx with GHA layer cache, **build-only, no push** — `linux/amd64` on every push/PR, `linux/arm64` under QEMU on a weekly cron + `workflow_dispatch` only, because the repo is private (no free native arm runners) and the emulated llama.cpp compile exceeds the 45-min practicality line (decision documented in the workflow header). Closes the standing "multi-arch build deferred to CI" gap (HANDOFF.md §2; bug #51). The parked draft `ci/ci.yml` is marked superseded and kept as the repo-split reference.

## [0.12.4] - 2026-06-10
### Changed
- **ADR-0011: Maude (claudeTalk iOS) is the v1 client; Flutter re-scoped to v2.** Supersedes ADR-0005 for MVP scope (Eddie 2026-06-10). Sprint 2 removed from the MVP critical path — now S1 ✅ → S3 remainder (TLS-default fleet verification) → S4 (CI/packaging/release). ROADMAP/PROJECT_PLAN/root PLANS.md updated; `clients/app/` Flutter skeleton stays, marked v2.

## [0.12.3] - 2026-06-10
### Fixed
- **Post-demo tightening (bug #53).** Plain-HTTP registry registration now fails fast unless `BARDPRO_ALLOW_INSECURE_HTTP=true` (startup WARNING when opted in; unknown schemes rejected). Agent container runs as non-root `bard`, no baked ssh host keys, no sshd in MVP, `EXPOSE 8444` only. Demo `podman run` flags add `--cap-drop=all --security-opt=no-new-privileges --read-only --tmpfs /tmp --pids-limit=512`. SELinux fine-grained grants remain roadmap (features #48).

## [0.12.2] - 2026-06-10
### Added
- **Demo one-page leave-behind** (`docs/demo/ONE_PAGER.md`): the 15-minute five-beat walkthrough (fleet, pool, live job, open-and-safe, Red Hat fit) with the real 3-node fleet table, honest real-vs-roadmap framing, and bring-up commands. Companion to `docs/demo/RUNBOOK.md` (Phase 4.1 deliverable).

## [0.12.1] - 2026-06-10
### Changed
- **NFR-2 reframed** (`BARD_LLM_PRO_MVP_SPEC.md`): the routed-request latency goal "≤ 500 ms on a local network" is now "router overhead negligible relative to model inference; target < 50 ms added latency on a local network". Docs only — no code change.

## [0.12.0] - 2026-06-10
### Added
- **Prometheus /metrics + structured JSON logging (feature #55).** `GET /metrics` on router, registry, and agent apps (Prometheus text exposition; unauthenticated like `/healthz`, standard scrape practice; additive in all three contracts). Shared `common/metrics.py` helper: `http_requests_total{service,path,status}` and `http_request_duration_seconds{service,path}` via Starlette middleware (route-template path labels, raw-path fallback for 404s, `/metrics` itself excluded), plus agent-side `inference_requests_total{backend,outcome}`. Per-app `CollectorRegistry` — never the global default — and an injectable clock. New dependency (pre-approved): `prometheus-client>=0.20,<1.0` (Apache-2.0, pure Python, ARM-fine). Structured logs via stdlib-only `common/logging.py`: `JsonFormatter` emits one JSON object per line (ts/level/logger/msg + extras + exc_info); `BARDPRO_LOG_FORMAT=json` (default) `|text`, wired into all three entrypoints. 156 tests, 100% branch cov.

## [0.11.0] - 2026-06-10
### Added
- **Registry agent liveness (feature #54)** — heartbeat, `lastSeen`, stale exclusion. The agent (when `BARDPRO_SELF_REGISTER=true`) re-POSTs `/register` every `BARDPRO_HEARTBEAT_INTERVAL_S` (default 15 s) as a background asyncio task started/cancelled by the app lifespan; failures are logged and non-fatal. The Registry stamps a server-side `lastSeen` on every successful `/register` and computes `status` (`active`|`stale`) at read time: stale once `now - lastSeen > BARDPRO_AGENT_TTL_S` (default 45 s = 3 missed beats). Stale agents stay visible in `GET /agents` / `GET /agents/{id}` (observability — never hard-deleted) but are excluded from `GET /pool` aggregation and `GET /schedule` placement. No new endpoints — the frozen registry contract gains only additive `lastSeen`/`status` fields. Clock and sleep are injectable; the 17 new tests never sleep. 139 tests, 100% branch cov.

## [0.10.0] - 2026-06-09
### Added
- **Cloud node (scale-to-zero) on Google Cloud Run** — the "any cloud" demo beat. Slim UBI+Podman echo agent (agent/Containerfile.cloud, no llama), built with **podman** (amd64), pushed to Artifact Registry, deployed to Cloud Run with **--min-instances=0** ($0 idle, cold-start on demand). JWT secret in **Secret Manager** (not plaintext); public but JWT-gated. The Mac registers it by its public URL (Cloud Run cannot reach the on-prem Tailscale registry). Verified: 3-node hybrid pool (Mac M5 Max + gx10 GB10 + Cloud Run); a job lands on the cloud node and echoes; real model inference still lands on the GB10. RUNBOOK updated.

## [0.9.0] - 2026-06-09
### Added
- **One-command demo bring-up/teardown + runbook.** scripts/demo_up.sh stands up the whole real Tailscale fleet (build agent image on Mac+gx10, serve-mode, both agents self-registering, dashboard, .env.local) and polls until the fleet registers; scripts/demo_down.sh tears it down; docs/demo/RUNBOOK.md captures the architecture, the 5-beat story, and the honest limitations (GPU advertised-not-yet-harnessed, Mac fleet-only, permissive MVP). gx10 uses a persistent model volume so re-runs are fast.

## [0.8.2] - 2026-06-09
### Fixed
- demo_serve router moved to **:9443** (Tailscale owns :8443 on the Mac TS IP). Live demo now runs a real 2-node Tailscale fleet — Apple M5 Max (Mac) + NVIDIA GB10 (gx10) — with real llama.cpp inference landing on the GB10.

## [0.8.1] - 2026-06-09
### Changed
- **MVP = permissive container permissions** (Eddie 2026-06-09); the fine-grained SELinux default-deny sandbox (#48) is the v2/v3 hardening roadmap, not enforced in the demo. Dashboard node badge corrected from "SELinux · default-deny" to the honest "rootless · UBI 9 · Podman"; demo plan beat 4 reframed accordingly (don't badge nodes default-deny in the MVP).

## [0.8.0] - 2026-06-09
### Added
- **Live-demo serve-mode** (`scripts/demo_serve.py`): runs Registry+Router on the Mac over plain-HTTP+CORS bound to 0.0.0.0 so real UBI+Podman agents on the Mac and **gx10 (NVIDIA GB10)** self-register over **Tailscale**; prints the shared secret, a dashboard token, and the `podman run` commands per node. Agent self-register scheme is now configurable (`registry_scheme`, default https; demo uses http over the WireGuard-encrypted Tailscale hop). 122 tests, 100% branch cov.

## [0.7.1] - 2026-06-09
### Added
- CORS (`common/cors.py`, off by default) on the Registry/Router `create_app`, so the demo console (browser, localhost:5173) can read `/agents`,`/pool`,`/schedule` and POST `/v1/message` over plain-HTTP. 122 tests, 100% branch cov.

## [0.7.0] - 2026-06-09
### Added
- **Demo Phase 3 (scaffold) — stranded-compute console** (`clients/demo-console`). Reuses
  cdn-sim's React 19 + Vite theme/chrome (Red Hat-styled dark theme + logo), drops the
  NOC-specific components, and adds a focused fleet/pool/job dashboard: a **pool KPI strip**
  (nodes · vCPUs · memory · GPU nodes, sustainability framing), a **fleet grid** of node
  cards (capability chips, specs, SELinux/rootless/default-deny badge, status light), and a
  **"Run inference (GPU-preferred)"** action that schedules → highlights the chosen node →
  shows the completion. Wired to `/agents`, `/pool`, `/schedule`, `/v1/message` with a SEED
  fallback so it renders standalone; live mode via `VITE_REGISTRY_BASE`/`VITE_ROUTER_BASE`/
  `VITE_TOKEN`. Slimmed deps (react/react-dom + vite/tsc); builds clean (tsc -b + vite).

## [0.6.0] - 2026-06-09
### Added
- **Demo Phase 1.5 — fleet harness** (`scripts/demo_fleet.py`). Stands up a real
  multi-node fleet on localhost TLS (Registry + Router + 4 heterogeneous agents with
  distinct power profiles) and exercises the whole demo chain end-to-end:
  register-with-capability → `GET /pool` → `GET /schedule` (GPU-preferred) →
  `POST /v1/message`. Verified PASS: 4 nodes · 32 cpus · 92 GiB · 1 GPU node; the
  gpu-preferred job lands on `gpu-workstation` and returns a completion. The integration
  proof for the Phase-1 backbone and the live data source for the demo dashboard.

## [0.5.0] - 2026-06-09
### Added
- **Demo Phase 1.4 — capability-aware placement.** `common/placement.py:select_agent`
  picks the best-fit node from the registered fleet (GPU-preferred, **CPU-fallback** =
  "any accelerator"; ranked GPU-first, then CPUs, then memory), exposed via the Registry's
  new `GET /schedule?gpu=<bool>` (the demo's "job lands on a capable node" beat). 121
  tests, 100% branch coverage. Contract: `/schedule` added to `registry.openapi.yaml`.

## [0.4.0] - 2026-06-09
### Added
- **Demo Phase 1.1 — agent self-registration on boot.** New `agent/register.py`: on
  startup the agent advertises itself (address + capability profile from a YAML
  power-profile + comma-separated capabilities) to the Registry, so heterogeneous nodes
  join the fleet on their own instead of being registered by the smoke script. Pure
  builders + an injectable httpx client (no network in tests). Config gains
  `self_register` (bool), `advertised_address`, `capabilities`; wired non-fatally into
  the agent entrypoint (logs + continues if the Registry is briefly down). 114 tests,
  100% branch coverage.

## [0.3.0] - 2026-06-09
### Added
- **Demo Phase 1 — registry capability persistence + pooled-capacity view.** The registry
  store now **persists** a registered agent's `powerProfile` (it was validated then dropped)
  and aggregates the fleet via a new `GET /pool` endpoint → total CPUs, memory bytes, and
  GPU-node count (`common.power.aggregate_pool` / `parse_memory_bytes`). This is the
  "stranded compute → pool" backend the demo dashboard reads. 102 tests, 100% branch cov.
### Changed (contract — deliberate extension for the demo)
- `contracts/registry.openapi.yaml`: added the `/pool` path + `PoolCapacity` schema and
  surfaced `powerProfile` on `AgentRecord`. Evolving the (previously frozen) registry
  contract is an intentional step for the MVP→demo pivot, not a lane patch.

## [0.2.2] - 2026-06-09
### Added
- `plans/PLAN_chris_demo.md` — MVP pivot toward a 15-min Red Hat CTO demo
  ("stranded compute → open inference pool"): 5-beat storyboard, reuse-vs-build, and a
  phased plan (fleet+capability = retargeted Sprint 3 · open Granite model · cdn-sim
  fleet/pool/live-job dashboard · dry run). Registered in `PLANS.md`.
- `docs/outreach/chris-wright-intro-email.md` — tailored 15-min intro email (saved).

## [0.2.1] - 2026-06-09
### Added
- **Python test suite driven to 100% branch coverage** (now-mandatory coverage gate).
  Added `pytest-cov` (MIT, pure-Python, ARM-clean) to `dev` deps and a
  `[tool.coverage.run] branch = true` config wired through `pytest` `addopts` with
  `--cov-branch --cov-report=term-missing --cov-fail-under=100`. New tests:
  `tests/test_clients.py` (real `HttpRegistryClient`/`HttpAgentClient` against a faked
  `httpx` transport — success, 404, 4xx/5xx, transport-error, and URL/scheme handling
  branches), `tests/test_config.py` (every `load_config` source + precedence + coercion +
  `require` branch), and `tests/test_coverage_gaps.py` (auth empty-secret/from_config/
  issuer-less paths, power-profile memory validation, version-resolution fallbacks,
  identity signing, no-persistence store, and the previously-unhit health/version/error
  endpoints on all three FastAPI apps). Tightened `tests/test_contracts.py` /
  `tests/test_e2e.py` to remove unreachable defensive lines. 89 tests green (was 36),
  100.00% branch coverage, no real network in unit tests.
### Changed
- `[tool.coverage.run] omit` excludes the three uvicorn entrypoints
  (`router/main.py`, `registry/main.py`, `agent/main.py` — branchless module-level
  `load_config()` + `create_app(...)` wiring whose factories are tested directly) and
  the dev-only TLS tooling `tests/fakes/gen_test_certs.py`. No product logic is omitted.

## [0.2.0] - 2026-06-09
### Added
- **Sprint 2 — Flutter client wired to the Router/Registry against the frozen contracts**
  (features.md #40). New `protocol.dart` (Dart domain model derived 1:1 from
  `protocol.schema.json`, strict parse-time validation), `config.dart` (router/registry
  URL + auth token via a config layer), and a refactored `api.dart` with an injectable
  `http.Client` seam and a typed error envelope (`error/retry/detail`). Model list ←
  Registry `GET /agents`; chat → Router `POST /v1/message`; every error branch handled
  (401/404/501/400/`502 agent_unavailable`). 71 tests green (was 4), `flutter analyze`
  clean, 100% line coverage of the new logic, no real network in tests, no new deps.
- Live on-device run against a running Router is deferred to Sprint 3 (integration);
  macOS desktop runner registration and `shared_preferences` persistence remain flagged.

## [0.1.7] - 2026-06-09

### Added
- `PROJECT_PLAN.md` — dependency-aware sprint plan to MVP (HANDOFF §4 ask): critical path
  (S1→S3→S4) vs parallel lanes (Flutter S2, coverage-to-100%, CI), per-sprint quality gates
  (contract-first, 100% branch coverage, green-before-commit, healthy-before-handover),
  current branch-coverage baseline (82%). Registered in root `PLANS.md`.

## [0.1.6] - 2026-06-09

### Fixed
- **Sprint-1 agent container now builds and runs on a real machine** (bugs.md #51). The
  runtime-stage `dnf install … libcurl` failed on UBI9 aarch64 because the
  `ubi9/python-311` base ships `libcurl-minimal`, which conflicts with the full `libcurl`
  that `llama-server` (built `-DLLAMA_CURL=ON`) needs. Added `--allowerasing` so dnf swaps
  minimal→full. Verified end-to-end on arm64: `podman build` succeeds; the container boots,
  llama-server loads the model and passes its health gate, the agent `/healthz` returns 200,
  and `POST /infer` returns a real llama.cpp completion (not the echo engine).

## [0.1.5] - 2026-06-09

### Added
- `HANDOFF.md` — handoff doc for local Claude to continue the work outside the
  (resetting) cloud sandbox: what's done (Sprint 0 + Sprint 1), how to run/test,
  the CI-deferred verifications to run on a real machine, what's next, open
  decisions, and the conventions.

## [0.1.4] - 2026-06-09

### Changed (docs)
- `README.md` updated to Sprint-1 reality: real llama.cpp inference (not "echo
  only"), 36 tests, a "run with a real model" quickstart, inference config rows,
  and an honest client status (Flutter skeleton; router wiring is Sprint 2; ssh
  tab/remote-spawn/trust layer are post-MVP). Removed the overclaimed
  "ssh-backed terminal" client line.
- `ROADMAP.md` marks **Sprint 1 code-complete** (build/live-run CI-deferred).

## [0.1.3] - 2026-06-09

Sprint 1 integration polish.

### Added
- End-to-end integration test (`tests/test_engine.py`): `/infer` → JWT →
  `LlamaCppEngine` → (mocked) llama server returns a real completion through the
  agent HTTP app. 36 tests green.

### Changed
- `scripts/smoke_local.py` is **backend-aware**: selects the engine via
  `make_engine` from `BARDPRO_INFERENCE_BACKEND` (env), so the same real-TLS smoke
  proves either the echo path (exact assert) or a co-located llama.cpp server
  (non-empty completion assert). Echo behaviour unchanged.

## [0.1.2] - 2026-06-09

Sprint 1 / tasks 1b + 1c + integration — the agent container builds and serves a
real llama.cpp model end-to-end (build authored here; the multi-arch build + live
model run are verified in CI / integration, not this sandbox).

### Added
- **Multi-stage `agent/Containerfile`** (1b): builder stage compiles llama.cpp's
  `llama-server` (pinned `LLAMACPP_REF`, portable CPU build `-DGGML_NATIVE=OFF`,
  `-DLLAMA_CURL=ON`) for the native `podman buildx` arch; runtime stage copies the
  binary to `/usr/local/bin/llama-server` + its shared libs (ldconfig). CUDA/GPU
  build noted as a follow-up.
- **`scripts/fetch_model.sh` + `.ps1`** (1c): config-driven GGUF download
  (`BARDPRO_MODEL_URL`, default Qwen2.5-0.5B-Instruct Q4_K_M, Apache-2.0, ~350 MB)
  into `${BARDPRO_MODEL_DIR}/model.gguf`; idempotent, atomic temp-file, optional
  SHA-256 verification, fails loudly.
- **`.env.example`**: `BARDPRO_MODEL_URL`, `BARDPRO_MODEL_SHA256`, `BARDPRO_LLAMA_THREADS`.

### Changed
- **`agent/entrypoint.sh`** (1c): on `BARDPRO_INFERENCE_BACKEND=llamacpp`, fetches the
  model if missing, launches `llama-server` on `127.0.0.1:8080`, and waits for
  `/health` (bounded retry, surfaces an early crash) before starting the API; `echo`
  path is unchanged.
- **Integration reconcile**: Containerfile copies `scripts/` into the image and
  `VERSION` into the build context (hatchling dynamic version); entrypoint resolves
  the fetch script via an overridable absolute path (`BARDPRO_FETCH_SCRIPT`,
  default `/opt/bardpro/scripts/fetch_model.sh`) instead of a broken relative path.

### Deferred to CI (Lane E / Sprint 4)
- Real `podman buildx` multi-arch build (amd64+arm64), `shellcheck`/`pwsh` lint of the
  scripts, and a live model smoke (download → `/v1/chat/completions`). Confirm the
  pinned `LLAMACPP_REF` and the HF model URL on the first real build.

## [0.1.1] - 2026-06-09

Sprint 1 / task 1a — real inference engine wired behind the existing interface.

### Added
- `LlamaCppEngine` (`agent/engine.py`) — forwards a text request to a llama.cpp
  **OpenAI-compatible** server (`/v1/chat/completions`) over httpx; injectable
  client for testing. `InferenceError` for backend failures.
- `make_engine(config)` — config-driven engine selection (`echo` | `llamacpp`).
- Config fields `inference_backend`, `llama_base_url`, `llama_model`,
  `llama_api_key`, `inference_max_tokens`, `inference_temperature` (+ `.env.example`).
- `tests/test_engine.py` — completion mapping, unreachable/500/malformed →
  `InferenceError`, backend selection, and the agent app's `502 inference_failed`
  envelope (httpx mocked — no network, §9).

### Changed
- Agent (`agent/main.py`) selects the engine from config instead of hardcoding
  `EchoEngine`; `agent/app.py` maps `InferenceError` to a retryable
  `inference_failed` envelope.
- **Version single-sourced.** `VERSION` is now the only canonical version;
  `pyproject.toml` reads it dynamically (hatchling) and `common/version.py` falls
  back to it from source — no drifted copies (§11).

### Notes
- LiteLLM is intentionally **not** added to the agent image: the agent fronts an
  OpenAI-compatible server directly via the existing httpx dep. LiteLLM's
  multi-backend routing belongs at the Router (Lane A) and is a §13-gated dependency
  decision pending sign-off.

## [0.1.0] - 2026-06-09

Inaugural version for the incubating Bard subproject. Sprint 0 — scope
reconciliation and decision freeze (docs only; no code/contract changes).

### Added
- `ROADMAP.md` — crawl/walk/run tiers + Sprints 0–4 to MVP, locked MVP forks,
  ADR→tier map, TPM-optional device-assurance tiering.
- `VERSION` (this file's companion) — canonical version for the subproject.
- ADR-0001…0005 — MVP architecture decisions: JSON wire protocol, no-mesh MVP,
  UBI+Podman+llama.cpp agent, ssh-backed CLI tab (scheduled v2), Flutter
  cross-platform client (macOS/iOS-first, designed for Windows/Linux).

### Changed
- Trust layer (`TRUST_MODEL.md` + ADR-0006…0010) demoted to *Proposed — deferred
  to v2/v3 (direction only, not MVP)*, each tagged with a roadmap tier; "D1–D5
  accepted" reframed as accepted *direction for v3*.
- **TPM is optional** — two-tier device assurance (hardware-backed = high;
  software keystore = standard) across `TRUST_MODEL.md §3/§7/§9` and ADR-0009.
- Source-doc reconciliation in `BARD_LLM_PRO_ARCHITECTURE.md` + `_MVP_SPEC.md`:
  struck iSH-runs-a-container claims (iOS is a client only), de-duplicated the
  high-water-mark paragraph, clarified LiteLLM-is-the-router (vLLM/"Athena" is a
  backend), flagged mesh/voice/non-NVIDIA accel as out of MVP.
