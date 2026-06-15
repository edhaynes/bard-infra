# Plans — status

Per `shared-rules/process-rules.md §3`. One row per plan doc under `plans/`.

| Plan | Status | Remaining |
|---|---|---|
| [plans/PLAN_mvp.md](plans/PLAN_mvp.md) | Implemented, 2026-06-15 | MVP complete — see follow-ups below |

## Done (2026-06-15)

- **S0** — RUBRIC.md, bugs.md, PLANS.md, plan doc; pre-commit + gitleaks wired and green. (278cbb5, f89aa1c)
- **A1** — six bardLLMPro infra designs migrated to canonical INFRA-3..INFRA-8 entries; status reconciled. (dcf5675)
- **A2** — frogstation bootstrap runbook (`docs/runbooks/frogstation-bootstrap.md`), verifiable checklist. (9dc5cd2)
- **B** — INFRA-1 name resolution (MagicDNS): contract, validator, IP-swap test, 100% branch coverage (23 tests). (adc5991)

## Follow-ups (post-MVP, not started)

- Wire the validator into bardLLMPro `common/config.py` (cross-repo) so Router/Registry/Agent config accepts logical names.
- **INFRA-2** — self-hosted fabric DNS (registry-backed resolver / managed FQDN).
- Execute A2 against the live box (bootstrap frogstation); update `connectivity.md` facts.
- v2 builds: Quay (INFRA-4), Valkey control plane (INFRA-5), Ansible facts (INFRA-6).
