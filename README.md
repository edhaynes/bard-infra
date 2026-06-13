# bard-infra

Canonical home for the **infrastructure** behind the Bard zero-trust inference
fabric — the layer that is *how the platform works*, as distinct from the
plugins/capabilities users connect (the infra-vs-plugin boundary, bardLLMPro
feature #68).

This repo is **private**.

## Scope

Two halves, both consolidated here by decision (Eddie, 2026-06-13):

1. **Fabric infra** — the software/architecture infrastructure of the Bard
   fabric: name resolution (DNS), the LokNet outbound-broker transport, image
   distribution (Quay), the control plane (Valkey), config-management facts
   (Ansible), metrics/observability. Tracked in [`features.md`](features.md).
   Detailed per-feature design currently lives in
   `~/projects/VibeLLamaPhonograph/bardLLMPro/features.md` (the live BardPro
   engineering backlog) and migrates here over time.

2. **GPU fleet / connectivity** — the physical compute nodes that *are* the
   fabric's agents, and how to reach them. See
   [`connectivity.md`](connectivity.md) (moved from `shared-rules/`): the DGX
   Spark (`gx10`/`gladius`) and the Windows GPU box (`frogstation`), Tailscale
   MagicDNS naming, SSH conventions, and the per-host traps.

## Layout

```
bard-infra/
├─ README.md          # this file
├─ features.md        # infrastructure feature backlog
└─ connectivity.md    # GPU fleet host coordinates + how to reach them
```

## Conventions

- Tracking format per `shared-rules/process-rules.md §2` (features with date +
  `Open`/`In Progress`/`Completed` status).
- **No secrets in this repo** (it is private, but the rule stands): host
  coordinates, OS usernames, and **public** keys only — never private keys,
  tokens, or passwords. Pre-commit runs `gitleaks` (see
  `.pre-commit-config.yaml`); install it with `pre-commit install`.
