# Plans — status

Per `shared-rules/process-rules.md §3`. One row per **active** plan doc under
`plans/` (archived/retired docs live in `plans/archive/` and are NOT tracked
here). Living history + the "why" is in [`JOURNAL.md`](JOURNAL.md) — read that
first.

| Plan | Status | Remaining |
|---|---|---|
| [plans/PLAN_mvp.md](plans/PLAN_mvp.md) | Implemented, 2026-06-15 | MVP complete (S0/A1/A2/B landed) |
| [plans/PLAN_loknet.md](plans/PLAN_loknet.md) | Implemented, 2026-06-10 | Slices 1–3 done (v1.1–v1.3); public Cloud Run deploy is Eddie's to run; demo not rewired |
| [plans/PLAN_client_tabs.md](plans/PLAN_client_tabs.md) | Implemented, 2026-06-08 | Five-tab shell shipped; **superseded by Box-first trim** (features #85); persistence + remote lifecycle were follow-ups |
| [plans/PLAN_device_identity_mvp.md](plans/PLAN_device_identity_mvp.md) | Partial — Remaining: user+device rework | Device-only S1–S7 landed (ADR-0016); **superseded by ADR-0017 (user+device)**; rework is the active sprint (`PLAN_box_demo_sprint.md`) |
| [plans/PLAN_mesh_decoupling.md](plans/PLAN_mesh_decoupling.md) | Partial — Remaining: Phases 1–5 | INFRA-2; Phase 0 (resolver reconcile) done 2026-06-24; remaining: selector → registry resolver → Nebula substrate → LokNet default → ADR |
| [plans/PLAN_basement_mvp.md](plans/PLAN_basement_mvp.md) | In Progress | MVP = private group push-to-talk on the LokNet fabric. **Overlaps PLAN_mvp_sprint + PLAN_box_demo_sprint — consolidation flagged (Eddie's call).** |
| [plans/PLAN_mvp_sprint.md](plans/PLAN_mvp_sprint.md) | Backlog — scoped 2026-06-17, awaiting greenlight | "Make a box, share a link, talk." **Overlaps PLAN_basement_mvp — consolidation flagged.** |
| [plans/PLAN_box_demo_sprint.md](plans/PLAN_box_demo_sprint.md) | Backlog — scoped 2026-06-18, awaiting go | Batch S8 on-device fixes (#69/#70) + Box-first trim, then re-verify S8. The current demo-blocking path. |
| [plans/PLAN_fleet_facts_console.md](plans/PLAN_fleet_facts_console.md) | Partial — Remaining: S5 | Feature #91 node-tree console + ansible hardware facts (ADR-0018). S1–S4 done+committed (2daf4e4 backend, 05d3455 console); remaining: S5 live-verify against the real fleet + §14 screenshots. |
| [plans/PLAN_bardnet_fleet_test.md](plans/PLAN_bardnet_fleet_test.md) | Not Implemented — authored 2026-07-01 | Onboard every `connectivity.md` device in succession then ping all over bardnet. **Tier 1** (hermetic real-roster test, buildable now); **Tier 2** (live over physical boxes, gated on fleet bring-up: mac+gx10 ready, bullfrog/snoopy partial, beagle/barney blocked). |

## Archived (retired — not tracked above)

- `plans/archive/PLAN_chris_demo.md` — **DEAD 2026-06-27** (Eddie: "Chris Wright
  demo is dead"). A reduced demo ran at v0.8.0/0.8.1 (bug #53); the 15-min build
  plan is retired.
- `plans/archive/HANDOFF_bard-arch-completion.md` — **Complete** (B1–B8 all
  landed); archived 2026-06-27.

## Open flags (need Eddie)

- **MVP plan sprawl:** `PLAN_basement_mvp` / `PLAN_mvp_sprint` /
  `PLAN_box_demo_sprint` overlap. Recommend consolidating into one live MVP
  plan; archive the rest. Awaiting decision.
