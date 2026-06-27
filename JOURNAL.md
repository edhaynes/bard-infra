# Bard-infra — development journal

> **READ THIS FIRST at the start of every bard-infra session** — the fast path
> to current repo status, recent decisions, and live threads before touching
> `PLANS.md` / `bugs.md` / `features.md`. (Standing rule, Eddie 2026-06-27 —
> canon in `shared-rules/process-rules.md §5`.)

**How this journal works (the rules):**
- **Newest entry on top. Latest is greatest.** Each entry is timestamped; a
  newer entry **supersedes** older ones where they conflict. To retire a
  decision, you don't edit history — you add a newer entry that overrides it
  (e.g. "Chris Wright demo is dead" supersedes the demo plan). The most recent
  word wins; older entries stay as the record of what was once true.
- **Per-repo + cross-project.** This file is bard-infra's history. Portfolio /
  cross-project history lives in `~/projects/JOURNAL.md` (Jason-meta's, read
  when launched from the projects root).
- The trackers (`bugs.md`/`features.md`/`PLANS.md`) say *what*; this journal
  says *what happened and why*, in time order.

---

## 2026-06-27 16:29 EDT — status review, plan audit, journal system stood up

**Driver (Eddie):** "is bard-infra working?" → review plans → start keeping a
timestamped journal as the repo's living status/history.

**Is it working? — fabric YES, Box MVP not clean.**
- **Fabric core: working, verified.** Router + Registry + Agent up over real
  TLS, agent self-registers, JWT-authed `POST /v1/message` round-trips. v1
  "Crawl" MVP complete 2026-06-10 (`bardpro-v1.0.0`). 100% line+branch coverage
  (macOS+Linux). Swappable engine (echo/llamacpp), MagicDNS resolution, LokNet
  outbound broker. `VERSION` 1.5.6, active dev.
- **Box MVP (private group push-to-talk): NOT clean.** Four-client box join+ping
  smoke landed (`b666a20`), but on-device testing left 2 functional blockers:
  **#69** box owner can't ping their own box (owner not auto-added to
  membership), **#70** a self-registered device can't join another box ("device
  already exists"; fix on a parked branch). Plus #66 (UI sluggish, partly
  debug/wireless) and #71 (iPhone wireless deploy stalls — USB workaround).
  → Plumbing solid; the "make a box, peers join, PTT works" path needs #69+#70
  before a clean demo. Active sprint: `PLAN_box_demo_sprint.md`.

**Plan audit (process-rules §3) — PLANS.md was stale, now fixed.**
- 10 plan docs existed; only 3 were tracked. Rebuilt PLANS.md to cover all of
  them.
- **Chris Wright demo is DEAD** (Eddie 2026-06-27). A reduced demo did run at
  v0.8.0/0.8.1 (see bug #53), but the 15-min "Stranded Compute" build plan is
  retired → **moved to `plans/archive/PLAN_chris_demo.md`**.
- **Arch-completion handoff complete** (B1–B8 all ✅) → moved to
  `plans/archive/HANDOFF_bard-arch-completion.md`.
- **Open flag for Eddie:** MVP plan sprawl — `PLAN_mvp` (done),
  `PLAN_basement_mvp`, `PLAN_mvp_sprint`, `PLAN_box_demo_sprint` overlap.
  Candidate to consolidate into one live MVP plan; not done yet (don't
  delete/merge plans without a call).

**Open thread — "Mega Vulcan" (training; NOT scoped, do not guess the mechanism).**
- Idea (Eddie): use **bardnet** to contribute **spare LLM cycles** across fleet
  nodes toward **training** a model ("Mega Vulcan"). Contribution rides **a
  plugin running over Podman to run inference** (the agent's containerized
  `InferenceEngine`). Exact training mechanism is **unsettled**.
- Standing architecture position (Jason, for whoever picks this up): bard-infra
  is an *inference dispatch* fabric, not a trainer. If scoped, bring the
  training algorithm from existing low-comm distributed-training OSS
  (DiLoCo/OpenDiLoCo, Hivemind, PETALS) and use bard-infra as the secure mesh
  substrate + node registry underneath — do **not** write a training plane into
  this repo. Constraints to revisit: training is communication-bound (needs
  low-comm methods over a mesh); spare *inference* cycles ≠ training memory
  (~3–4× more); one real training-capable node today (Gladius/gx10, 128 GB
  unified, ARM64). "Run"-horizon, downstream of the Box MVP. Filed: features #90.

**Process changes shipped this session.**
- This journal created; "read at session start" + "newest/latest-is-greatest
  supersession" conventions defined.
- Canon updated: `shared-rules/process-rules.md §5` (JOURNAL system, all repos).
- **Deferred (next focused pass, not done — kept scope tight per Eddie):**
  iron-fist hook teeth (extend `check_plan_tracker_status.py` to fail commits
  when a plan isn't tracked in PLANS.md or `JOURNAL.md` is missing); the
  cross-project `~/projects/JOURNAL.md`; rollout to the other repos.
