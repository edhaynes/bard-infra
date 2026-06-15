Status: Implemented, 2026-06-15 — S0, A1, A2, B all landed (commits f89aa1c..adc5991)
Author: Jason-infra

# bard-infra MVP

## Thesis

The fabric **software** already shipped (bardLLMPro v1.0.0, 2026-06-10):
Router + Registry (JSON-file) + Agent (real llama.cpp) over TLS+JWT, with
heartbeat/TTL (#54), Prometheus metrics + JSON logs (#55), and LokNet
outbound-broker transport (#59, slices 1–3, real-socket proven). Contracts are
frozen in bardLLMPro `contracts/*.openapi.yaml`.

So this MVP is **not** rebuilding Router/Registry/Agent. It makes bard-infra the
**authoritative infrastructure home** and delivers the one net-new infra
capability — **name resolution** (INFRA-1) — leaning on the MagicDNS that
already resolves the fleet. No live-deploy risk; every sprint ships
independently.

## Decisions (Eddie, 2026-06-15)

1. **Center of gravity:** Ops home + INFRA-1 (both tracks below).
2. **Name resolution backend:** MagicDNS-only for the MVP. Self-hosted DNS is
   the target state but post-MVP — see `features.md` INFRA-2.

## Sprints

Each sprint is independently shippable and sized to land first-try.

### S0 — Process baseline
Bring the repo up to our own §18 bar before feature work.
- `RUBRIC.md` (how infra quality is graded), `bugs.md`, `PLANS.md`, this plan.
- **Install pre-commit hooks** — `gitleaks` and `pre-commit` are not installed
  on this machine yet (verified 2026-06-15); §7.1 requires hooks before the
  first commit. `pre-commit install`; confirm a clean run.
- **Done-signal:** files exist; `pre-commit run --all-files` passes clean.

### A1 — Migrate infra designs from bardLLMPro
Pull the full design text for the six "(migrate)" items into `features.md` and
reconcile status against bardLLMPro reality. No `(migrate)` placeholders left.
- LokNet #59 → **Completed**; Prometheus #55 → **Completed**;
  Heartbeat/TTL #54 → **Completed**.
- Quay #53 → **Open** (v2); Valkey control plane → **Open** (v2, ADR-0010);
  Ansible facts → **Open**.
- **Done-signal:** every migrate item has a real dated entry with the correct
  status; numbering reconciled with bardLLMPro; no placeholders.

### A2 — frogstation bootstrap runbook
`connectivity.md` flags frogstation is a bare fresh Windows image (SSH :22,
ComfyUI :8188, RDP :3389 all refused). Turn the prose bootstrap into a numbered,
verifiable checklist; mark which steps need Eddie at the console/RDP (the Mac
cannot SSH in to enable SSH).
- **Done-signal:** ordered checklist; each step has a verify command;
  Mac-vs-console steps labeled.

### B — INFRA-1 name resolution (MagicDNS)
Net-new capability, scoped to land entirely in this repo.
- **B1 — Contract:** freeze the name-resolution contract — fabric config is
  addressed by stable logical names; resolution via MagicDNS; raw fabric IPs
  are rejected.
- **B2 — Validator:** a startup validator that fails fast when a logical name
  does not resolve, or when a raw fabric IP is pinned where a name is required.
- **B3 — Test:** IP-swap regression harness — swap a node's address, assert the
  fabric still resolves it by name. 100% line + branch coverage (`--cov-branch
  --cov-fail-under=100`).
- **Cross-repo follow-up (NOT MVP):** wiring the validator into bardLLMPro
  `common/config.py` so Router/Registry/Agent config accepts logical names.
  Tracked, sequenced after the MVP lands.
- **Done-signal:** B3 passes; coverage gate green; contract documented.

## Out of scope (this MVP)
- Standing up the live persistent fabric (Cloud Run front door, always-on
  fleet) — separate operational push.
- Self-hosted DNS (INFRA-2), registry-backed resolver, managed public FQDN.
- Quay / Valkey / Ansible implementation (designs migrate in A1; build is v2).
- bardLLMPro config wiring for INFRA-1 (cross-repo follow-up).
