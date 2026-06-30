# RUBRIC — Refinery Self-Discovery Demo

Working bar 90%; polish to 95%; nothing "ships" (is shown as the QNX demo) below 95%.

| Dimension | Weight | What an A looks like |
|---|---|---|
| Self-discovery is real | 20% | Elements register into the **real** bard-infra Registry; killing heartbeat → real `stale`; no faked discovery |
| Believable refinery | 15% | Baytown-mapped sections/units, realistic tags + telemetry ranges, SIS modeled as a parallel chain |
| Bring-up / bring-down | 20% | Ordered, interlock-gated, visualized; reverse shutdown; SIS-respecting |
| Failure handling | 20% | Inject → detect → cascade (loss-of-steam, switch-blind, gas→SIS trip) → fail-safe → remediate |
| Console clarity | 15% | A non-OT viewer reads the 5 sections, live state, and the operation in progress at a glance |
| Engineering quality | 10% | 100% line+branch coverage (Python), Playwright structure tests, secret-free public repo, fail-fast config |

Score = Σ(weight × dimension%). Track per-sprint in `JOURNAL.md`.
