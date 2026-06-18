# bard-infra — the Bard zero-trust inference fabric

**Bard** is a self-hosted **inference fabric** for the home power user and the
small business: a control + data plane that pools the compute you already own
(a desktop, a GPU box, an old server, a laptop) into one fleet, then dispatches
inference requests to whichever node can serve them — **without anything
leaving your network**. The LLM is *not* the product; it is one **plugin**
(an `InferenceEngine` backend) that connects on top of the platform. SSH,
remote desktop, a walkie-talkie (Squawk Box), and storage are siblings of the
LLM on the same seam.

This repo is the **canonical home of the whole fabric** after the
bardLLMPro → bard-infra re-home (commit a9caafd; the `bardLLMPro` name is
retired). The router, registry, agent, the trust/identity layer, the management
console, the clients, and the name-resolution package all live here. **This
repo is private.** Pre-split history is frozen at tag
`archive/pre-infra-split-2026-06-18` in the `bard-llm` repo.

> Who is it for? A technically-confident owner of more than one machine who
> wants Tailscale-style "add a device, approve it, use it" simplicity over a
> control plane that is **theirs** — no third-party coordination server, the
> Profile A posture of *nothing leaves the network*.

---

## Quick start

Prereqs: **Python ≥ 3.11**, [`uv`](https://docs.astral.sh/uv/), `git`.
(`pre-commit` + `gitleaks` are required before your first commit — see
[Contributing](#contributing).)

```bash
git clone git@github.com:edhaynes/bard-infra.git
cd bard-infra
uv sync --extra dev          # creates .venv and installs runtime + dev deps
```

### One command (recommended) — a real localhost TLS fleet end-to-end

```bash
./scripts/run_local_mac.sh   # macOS + Linux: Registry + Agent + Router on
                             # localhost TLS, registers the agent, mints a JWT,
                             # sends a message through the Router, prints the
                             # round trip. The "running on the box" proof.
```

### Run the three services by hand

Each service is a FastAPI app served by `uvicorn`. **`BARDPRO_JWT_SECRET` is
required at startup** (≥ 32 bytes — the services fail fast otherwise). Use the
same secret for every process in one fleet.

```bash
export BARDPRO_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Registry — the fleet's source of truth (agents, devices, channels, plugins).
uv run uvicorn registry.main:app --host 127.0.0.1 --port 8081

# Agent — wraps an inference backend (echo | llamacpp) and self-registers.
BARDPRO_SELF_REGISTER=true BARDPRO_INFERENCE_BACKEND=echo \
  uv run uvicorn agent.main:app --host 127.0.0.1 --port 8444

# Router — the public front door; clients POST /v1/message here.
uv run uvicorn router.main:app --host 127.0.0.1 --port 8443
```

Health/readiness is `GET /healthz` on every service; `GET /version` reports the
build. A client request is `POST /v1/message` to the Router (Bearer JWT).

### Run the tests

```bash
uv run --extra dev python -m pytest      # 100% line + branch coverage gate
```

The gate is wired in `pyproject.toml` (`--cov-branch --cov-fail-under=100`); a
run below 100% fails. Tests run on macOS and Linux.

---

## Configuration

All config flows through one layer (`common/config.py`): defaults < OS env vars
< `.env` < YAML config file < CLI overrides. Every key is an environment
variable prefixed **`BARDPRO_`** (e.g. the `jwt_secret` field is
`BARDPRO_JWT_SECRET`). Validation is fail-fast at startup. The table below is
the full `Config` surface (source: `common/config.py`).

| Env var (`BARDPRO_…`) | Default | Description | Required? |
|---|---|---|---|
| `ROUTER_HOST` | `127.0.0.1` | Router bind host | no |
| `ROUTER_PORT` | `8443` | Router bind port (public front door) | no |
| `REGISTRY_HOST` | `127.0.0.1` | Registry bind host | no |
| `REGISTRY_PORT` | `8081` | Registry bind port (private) | no |
| `REGISTRY_SCHEME` | `https` | Scheme the agent self-registers with; `http` needs the opt-in below | no |
| `ALLOW_INSECURE_HTTP` | `false` | Opt-in for cleartext `http`/`ws` (only over an already-encrypted hop, e.g. Tailscale) | no |
| `AGENT_HOST` | `127.0.0.1` | Agent bind host | no |
| `AGENT_PORT` | `8444` | Agent bind port | no |
| `TLS_CERT_PATH` | _none_ | Path to TLS cert (key material never lives in config) | no |
| `TLS_KEY_PATH` | _none_ | Path to TLS private key | no |
| `JWT_SECRET` | _none_ | HMAC signing secret for fleet JWTs; **≥ 32 bytes (RFC 7518 §3.2)** | **yes** |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm | no |
| `JWT_ISSUER` | `bardllm-pro` | Expected `iss` claim | no |
| `DEVICE_IDENTITY_ENABLED` | `false` | Opt-in per-device identity (enrollment lifecycle, per-device keys) vs the fleet-wide shared secret | no |
| `DEVICE_STORE_PATH` | `./device-state.json` | JSON persistence for device records | no |
| `DEVICE_JOIN_SECRET` | _none_ | HMAC key signing join tokens; **≥ 32 bytes** | when device identity on |
| `DEVICE_JOIN_TOKEN_TTL_S` | `900` | Join-token lifetime (s) | no |
| `DEVICE_TOKEN_TTL_S` | `3600` | Per-device token lifetime (s) | no |
| `DEVICE_SECRET` | _none_ | This agent's own per-device HMAC secret (agent side only) | no |
| `CHANNEL_INVITE_SECRET` | _none_ | HMAC key signing single-use channel invites; **≥ 32 bytes** | when device identity on |
| `CHANNEL_INVITE_TTL_S` | `604800` | Invite lifetime (s; 7 days) | no |
| `INVITE_BASE_URL` | _none_ | Public link/QR landing the invite token is embedded into | when device identity on |
| `AUDIT_LOG_PATH` | `./audit-log.jsonl` | Append-only JSONL of console management actions | no |
| `PLUGIN_CATALOG_DIR` | `./examples/plugins` | Dir of `*.manifest.json` plugin manifests | no |
| `PLUGIN_STATE_PATH` | `./plugin-state.json` | Per-plugin enable/config/health persistence | no |
| `PLUGIN_HEALTH_TTL_S` | `45` | Freshness window for reported plugin health (s) | no |
| `AGENT_ID` | `agent-local` | This agent's logical id (`sub` of its token) | no |
| `MODEL_DIR` | `./models` | Local model directory | no |
| `REGISTRY_STATE_PATH` | `./registry-state.json` | JSON persistence for the agent registry | no |
| `POWER_PROFILE_PATH` | _none_ | Path to this node's capability/power profile | no |
| `SELF_REGISTER` | `false` | Agent advertises itself to the Registry on boot | no |
| `ADVERTISED_ADDRESS` | _none_ | Address peers reach this agent at (defaults to `agent_host:agent_port`) | no |
| `CAPABILITIES` | _none_ | Comma-separated capability tags (e.g. `gpu,llm`) | no |
| `HEARTBEAT_INTERVAL_S` | `15` | Agent re-`POST /register` heartbeat interval (s) | no |
| `AGENT_TTL_S` | `45` | Registry marks an agent stale past this TTL (s) | no |
| `BROKER_ENABLED` | `false` | Opt-in LokNet outbound agent link (no inbound ports) | no |
| `BROKER_URL` | _none_ | Router `wss://…/v1/agent-link` endpoint | when broker on |
| `BROKER_BACKOFF_INITIAL_S` | `1.0` | Broker reconnect backoff floor (s) | no |
| `BROKER_BACKOFF_MAX_S` | `60.0` | Broker reconnect backoff cap (s) | no |
| `ENFORCE_PEER_NAME_RESOLUTION` | `true` | Peer addresses must be resolvable logical names, not raw IPs | no |
| `INFERENCE_BACKEND` | `echo` | Inference engine: `echo` (fake) or `llamacpp` | no |
| `LLAMA_BASE_URL` | `http://127.0.0.1:8080/v1` | llama.cpp OpenAI-compatible base URL | no |
| `LLAMA_MODEL` | `local-gguf` | Model name passed to the llama.cpp backend | no |
| `LLAMA_API_KEY` | _none_ | API key for the llama.cpp backend (if any) | no |
| `INFERENCE_MAX_TOKENS` | `512` | Max tokens per completion | no |
| `INFERENCE_TEMPERATURE` | `0.7` | Sampling temperature | no |
| `LOG_LEVEL` | `INFO` | Log level | no |
| `LOG_FORMAT` | `json` | `json` (structured) or `text` | no |
| `REQUEST_TIMEOUT_S` | `30.0` | Outbound HTTP request timeout (s) | no |

---

## Architecture

The fabric is a **control plane** (who is in the fleet, what they can do) and a
**data plane** (route a request to a capable node) sharing one config layer and
one set of frozen contracts.

- **`router/`** — the public front door and data-plane dispatcher. Verifies the
  caller's token, looks the target agent up in the Registry, and forwards
  `POST /v1/message` to it. Hosts the LokNet broker endpoint
  (`/v1/agent-link`) so agents can serve over a single outbound WebSocket with
  no inbound reachability.
- **`registry/`** — the fleet's source of truth: agent records + liveness
  (heartbeat/TTL), the device enrollment lifecycle, channel/box membership,
  the plugin catalog/state, and the append-only management audit log.
- **`agent/`** — runs on each fleet node. Wraps a swappable `InferenceEngine`
  (`echo` | `llamacpp`), self-registers, heartbeats, and optionally dials the
  broker. The LLM is just the engine this agent happens to host.
- **`common/`** — the shared spine: `config.py` (the one config layer),
  `auth.py` / `device_auth.py` (JWT + per-device verification), `protocol.py`,
  `placement.py`, `power.py`, `metrics.py`, `logging.py`, `name_resolution.py`.
- **`bard_infra/nameres/`** — name-resolution package (INFRA-1). Fabric peers
  are addressed by **stable logical names**, never raw IPs; `resolver.py` is the
  swap seam (`SystemResolver` over Tailscale MagicDNS today), `validator.py`
  fails fast on a raw-IP peer or an unresolvable name.
- **boxes / channels** — the "send a link, you're in" onboarding primitive
  (`registry/channel_store.py`, `contracts/invite.schema.json`): single-use
  expiring invites that admit a device to a channel/box with no account. The
  same invite primitive serves both fleet enrollment and Squawk Box channels.
- **identity / trust** — per-device identity (`common/device_auth.py`,
  `registry/device_store.py`, `contracts/enrollment.schema.json`) replaces the
  fleet-wide shared secret with per-device keys through
  join-token → pending → active → revoked. `trust/` holds the
  orgs → workgroups → devices model (`identity.py`, `group.py`, `member.py`,
  `control_plane.py`, `attestation.py`).
- **`clients/`** — `clients/app/` is the Flutter cross-platform client
  (Dashboard / Connections / Terminal / Chat).
- **`clients/console/`** — the React management console: Tailscale-style device
  enrollment, approve/revoke/rename, workgroup assignment, an activity (audit)
  pane, and the plugin manager — over a control plane that is yours.
- **`contracts/`** — the **frozen** API/schema contracts the code is written
  against (OpenAPI for router/registry/agent; JSON Schema for the broker link,
  enrollment, invites, plugin manifests, the protocol, the power profile;
  `trust.schema.yaml` + `control-plane.openapi.yaml` for the control plane).

---

## Deployment

- **Local / dev.** `scripts/run_local_mac.sh` (real localhost TLS) is the
  reference. `scripts/local_fleet_http.py` brings up an all-HTTP fleet for
  client wiring (requires `BARDPRO_ALLOW_INSECURE_HTTP=true`).
- **Containers.** `agent/Containerfile` builds the agent on **UBI-9** with
  Podman (multi-arch arm64 + amd64); the agent runs **non-root**, drops caps,
  and exposes only its port. `agent/Containerfile.cloud` /
  `router/Containerfile.cloud` are the Cloud Run variants (port 8080).
- **Fleet over Tailscale.** `scripts/tailscale_fleet_up.sh` brings the fabric up
  across the tailnet addressed **by MagicDNS name** with
  `ENFORCE_PEER_NAME_RESOLUTION=true`; see
  [`docs/runbooks/`](docs/runbooks/) for the demo runbooks.
- **Image distribution / HA** (Quay multi-arch + signing, Valkey control plane
  for multi-instance Router/Registry) are designed and tracked in
  [`features.md`](features.md) (INFRA-4, INFRA-5) — not yet built.

---

## Troubleshooting

- **`Missing required configuration: BARDPRO_JWT_SECRET`** — export a secret of
  **≥ 32 bytes** before starting any service; all three fail fast without it.
- **`registry_scheme=http` raises `ConfigError`** — cleartext is opt-in: set
  `BARDPRO_ALLOW_INSECURE_HTTP=true`, and only over an encrypted hop (Tailscale).
- **Router `POST /v1/message` → 502 `agent_unavailable`** — the Router can't
  reach the agent: the agent didn't self-register, is stale past its TTL, or a
  scheme mismatch broke the registry lookup (see bugs.md #60). Check the
  Registry `/agents` list and the agent's `/healthz`.
- **`RawIPError` / `NameResolutionError`** — a peer was addressed by raw IP, or
  the logical name doesn't resolve. Use the MagicDNS name (`gx10`, not the IP);
  confirm `tailscale status | grep <name>`. See `connectivity.md`.
- **Coverage gate fails the test run** — a branch is unexercised; the suite is
  pinned at 100% line + branch. Add the missing assertion, don't lower the bar.
- **Commit blocked by a hook** — read the gitleaks finding; never bypass with
  `--no-verify` if a real secret is flagged (§7).

---

## Contributing

```bash
pre-commit install        # gitleaks + hooks; required before the first commit (§7)
pre-commit run --all-files
```

- Tracking format per `shared-rules/process-rules.md §2`
  ([`features.md`](features.md), [`bugs.md`](bugs.md), [`PLANS.md`](PLANS.md)).
- **No secrets in this repo** (private, but the rule stands): host coordinates,
  OS usernames, and **public** keys only — never private keys, tokens, or
  passwords.
