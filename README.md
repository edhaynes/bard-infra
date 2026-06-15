# bard-infra

Canonical home for the **infrastructure** behind the Bard zero-trust inference
fabric — the layer that is *how the platform works*, as distinct from the
plugins/capabilities users connect (the infra-vs-plugin boundary, bardLLMPro
feature #68). **This repo is private.**

It is two things at once: the **authoritative index** of the fabric's
infrastructure (designs, status, runbooks — pointing at where each thing is
implemented), and a small amount of **net-new infra code** that doesn't belong
in the application repo (today: fabric name resolution).

## What's here

| Area | Where |
|---|---|
| Infra feature index (INFRA-1..INFRA-8) | [`features.md`](features.md) |
| GPU fleet coordinates + how to reach them | [`connectivity.md`](connectivity.md) |
| Frozen contracts | [`docs/contracts/`](docs/contracts/) |
| Operational runbooks | [`docs/runbooks/`](docs/runbooks/) |
| Name-resolution package | [`src/bard_infra/nameres/`](src/bard_infra/nameres/) |
| Quality bar / plan / trackers | `RUBRIC.md`, `plans/`, `PLANS.md`, `bugs.md` |

The fabric **software** (Router, Registry, Agent, LokNet transport, metrics,
heartbeat) ships from **bardLLMPro** — this repo indexes and reconciles its
infra status, it does not duplicate it.

## Quick start

Prereqs: Python ≥ 3.11, `git`. (For commits: `pre-commit` + `gitleaks` — see
*Contributing*.)

```bash
git clone git@github.com:edhaynes/bard-infra.git
cd bard-infra
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"   # Windows: .venv\Scripts\python.exe
```

Use the name-resolution validator (rejects raw IPs, fails fast on unresolvable
names, addresses the fabric by stable logical name):

```python
from bard_infra.nameres import validate_endpoint, SystemResolver

result = validate_endpoint("gx10:8080", SystemResolver())
print(result.name, result.port, result.addresses)   # gx10 8080 ('100.97.246.73',)
```

## Run the tests

```bash
.venv/bin/python -m pytest      # 100% line + branch coverage gate (pyproject)
```

## Configuration

This repo has **no runtime config of its own** — the name-resolution package is
a library consumed by the fabric. The values it validates are fabric endpoint
names that live in bardLLMPro's config layer (`BARDPRO_*`, e.g.
`BARDPRO_BROKER_URL`). The contract for what counts as a valid endpoint name is
frozen in [`docs/contracts/name-resolution.md`](docs/contracts/name-resolution.md).

| What | Default | Notes |
|---|---|---|
| Resolver backend | `SystemResolver` (OS / Tailscale MagicDNS) | Swappable `Resolver` ABC; INFRA-2 adds self-hosted DNS |
| Port range accepted | 1–65535 | Out-of-range or non-name host fails fast |

## Architecture

- **Name resolution (INFRA-1).** Fabric endpoints are addressed by stable
  logical names, never raw IPs. `Resolver` is the swap seam: `SystemResolver`
  (the OS resolver, served by MagicDNS) today; a registry-backed or self-hosted
  resolver (INFRA-2) later, with no caller change. `validate_endpoint` enforces
  the contract at startup and crashes loudly on a bad value.
- **Index, not copy.** `features.md` carries reconciled status + a source
  pointer for each migrated item (LokNet, Quay, Valkey, Ansible, metrics,
  heartbeat) so this repo never drifts from bardLLMPro.
- **Fleet.** `connectivity.md` is the single source of truth for the GPU hosts
  (gx10/gladius, frogstation) — MagicDNS names, SSH conventions, per-host traps.

## Deployment

The name-resolution package is a library, not a deployed service — it is
imported by the fabric (cross-repo wiring into bardLLMPro is a tracked
follow-up). Operational deployment of the fabric itself (Cloud Run Router front
door, bringing the GPU fleet up as agents) is out of scope for this MVP; the
frogstation bring-up is documented in
[`docs/runbooks/frogstation-bootstrap.md`](docs/runbooks/frogstation-bootstrap.md).

## Contributing

```bash
pre-commit install      # gitleaks + hooks; required before the first commit (§7)
pre-commit run --all-files
```

- Tracking format per `shared-rules/process-rules.md §2`.
- **No secrets in this repo** (private, but the rule stands): host coordinates,
  OS usernames, and **public** keys only — never private keys, tokens, or
  passwords.

## Troubleshooting

- **`validate_endpoint` raises `RawIPError`** — you passed a raw IP where a
  logical name is required. Use the MagicDNS name (`gx10`, not `100.97.246.73`).
- **`NameResolutionError`** — the name doesn't resolve. Check Tailscale is up
  and the host is on the tailnet (`tailscale status | grep <name>`); see
  `connectivity.md`.
- **`pip install -e` fails** — ensure Python ≥ 3.11 and you're in the venv.
- **Can't reach a fleet host** — work the triage ladder in `connectivity.md`
  ("host appears unreachable"); Windows boxes don't answer `ping`.
- **Commit blocked by a hook** — read the gitleaks finding; never bypass with
  `--no-verify` if a real secret is flagged (§7).
