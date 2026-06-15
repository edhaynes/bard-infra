# bard-infra quality rubric

How we grade the infrastructure layer. Per `shared-rules/coding-rules.md §11`:
**90% is the working bar** (solid A−), polish to **95%**, publish nothing below
**95%**. This rubric grades *infrastructure* — running fabric, name resolution,
runbooks, and the authority of this repo as the single source of truth — not
application/UX (that lives in bardLLMPro's rubric).

Each dimension is graded A–F and weighted. The score is the weighted average,
normalized to 100. A dimension at C or below on a shipped item is a stop-and-fix.

| # | Dimension | Weight | What an A looks like |
|---|---|---|---|
| 1 | **Correctness** | 20% | The infra does what it claims. Name resolution survives an IP swap with no config edit; validators reject exactly the bad cases and pass the good ones. Proven by test, not asserted. |
| 2 | **Fail-fast config** | 15% | Invalid config / unresolvable name / pinned raw IP is caught at startup with a clear, named error (§0.11). No limping in a degraded state; no silent fallback to a different backend. |
| 3 | **Secret hygiene** | 15% | Zero secrets in-repo (§0.2, §7). Host coordinates / OS usernames / **public** keys only. `gitleaks` + `pre-commit` installed and green on every commit; full push-range scan clean. |
| 4 | **Cross-platform / cross-arch** | 10% | Works across the real fleet: macOS client, Linux aarch64 (gx10/Grace-Blackwell), Windows (frogstation). No hardcoded paths/OS/shell (§5). Any dep has a maintained native ARM build (§13). |
| 5 | **Reproducibility** | 15% | Runbooks are numbered, verifiable checklists — every step has a verify command and a clear done-signal. A clean machine reaches a working state from the doc alone (NFR-4). Console-vs-remote steps labeled. |
| 6 | **Test & branch coverage** | 10% | New infra logic ships with tests; 100% line **and** branch coverage on the validator/resolution code (`--cov-branch --cov-fail-under=100`). Bug fixes ship a regression test written first. |
| 7 | **Single source of truth** | 10% | This repo is the canonical infra index. No `(migrate)` placeholders left where a real entry belongs; status reconciled against bardLLMPro reality; no contradictory duplicate of a fact that lives elsewhere. |
| 8 | **Observability** | 5% | Infra components expose health/readiness + `/metrics`; structured (JSON) logs; enough context in errors to diagnose without a re-run (§12). |

## Grading notes

- **Bar math:** A=95, B=85, C=75, D=65, F=50 per dimension; weighted-average ≥90
  ships internally, ≥95 publishes.
- **Veto conditions** (auto-fail regardless of weighted score): any secret in the
  repo or push range (dim 3 → F); a runbook step with no verify command that a
  human got wrong (dim 5); coverage gate disabled or below 100% on shipped
  validation code (dim 6).
- The rubric is itself versioned here; changes go through a commit, not a silent
  edit.
