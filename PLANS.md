# Plans — status

Per `shared-rules/process-rules.md §3`. One row per plan doc under `plans/`.

| Plan | Status | Remaining |
|---|---|---|
| [plans/PLAN_mvp.md](plans/PLAN_mvp.md) | Implemented, 2026-06-15 | MVP complete — see follow-ups below |
| [plans/PLAN_device_identity_mvp.md](plans/PLAN_device_identity_mvp.md) | In Progress | S1–S6 done (S6 box ping backend, 2026-06-18); S7 Flutter recovery client done (2026-06-18, feat/s7-flutter-recovery: key-derived deviceId + Argon2id/AES-GCM two-tier seed escrow + OMG one-screen + recovery flow); remaining S7 backend escrow store (parallel worktree), S8 (all-device sign-off) |
| [plans/PLAN_mesh_decoupling.md](plans/PLAN_mesh_decoupling.md) | Partial — Phase 0 done 2026-06-24 | INFRA-2 core: Phase 0 (resolver reconcile) done; remaining Phases 1–5 (selector → registry resolver → Nebula substrate → LokNet default → ADR) |

## Done (2026-06-15)

- **S0** — RUBRIC.md, bugs.md, PLANS.md, plan doc; pre-commit + gitleaks wired and green. (278cbb5, f89aa1c)
- **A1** — six bardLLMPro infra designs migrated to canonical INFRA-3..INFRA-8 entries; status reconciled. (dcf5675)
- **A2** — frogstation bootstrap runbook (`docs/runbooks/frogstation-bootstrap.md`), verifiable checklist. (9dc5cd2)
- **B** — INFRA-1 name resolution (MagicDNS): contract, validator, IP-swap test, 100% branch coverage (23 tests). (adc5991)

## Follow-ups

- **Done (on branch, pending review/merge)** — validator vendored + wired into
  bardLLMPro `common/config.py` behind opt-in `BARDPRO_ENFORCE_PEER_NAME_RESOLUTION`
  (default OFF). Peer addresses must be resolvable names; loopback + `broker://`
  sentinel exempt. 494 tests, 100% coverage. bardLLMPro branch
  `claude/laughing-bell-57o15u` commit `09605bb` — **not yet merged to bard-llm main.**
- **INFRA-2** — self-hosted fabric DNS (registry-backed resolver / managed FQDN). **Design frozen 2026-06-24: `plans/PLAN_mesh_decoupling.md` (Nebula substrate + registry resolver).**
- Execute A2 against the live box (bootstrap frogstation); update `connectivity.md` facts.
- v2 builds: Quay (INFRA-4), Valkey control plane (INFRA-5), Ansible facts (INFRA-6).
