Status: Backlog — scoped 2026-06-18, batch the S8 on-device fixes + Box-first trim, then re-verify S8. Awaiting go.

# Sprint — Box MVP demo-ready

Goal: the **Box** flow (private group identity + ping) works end-to-end on iPhone +
iPad, **trimmed to Box-only** (legacy Pro-client tabs out of scope, [[bard-one-app-plugins-scope]]),
with every S8 on-device bug fixed → **S8 §14 sign-off passes**. Deliberate batch, not
fix-on-the-fly. Builds on `PLAN_device_identity_mvp.md` (S1–S7 done; this is the road to S8).

## Already done (on main)
- **#68** box-screen freeze (Argon2id off the UI isolate) + Share/Copy — Completed (`e2cdd25`).

## Sprint items (sized per §18.5)

### B1 — Integrate the two parked fixes · ~0.5 d · FIRST (unblocks the rest)
Merge the ready branches, deliberately:
- `fix/join-existing-device-labels` (**#70** — a self-registered device can join another box; labels in the members response). Backend, 653 tests green.
- `feat/device-naming` (**#84** — first-run "Name this device" dialog; friendly names instead of `dev-…`). Frontend (finishing).
- Merge both → regenerate `.secrets.baseline` → green gate (Python + Flutter) → push. Verify the members/label contract meets between the two.
- **Done:** both on main, green; a device can own + join boxes, and names show instead of `dev-blah`.

### B2 — Fix #69: owner is a member of their own box · ~0.5 d · backend · ∥ with B3
- `registry/channel_store.py`: add the **owner's deviceId to `memberships`** at channel creation (today owner and membership are separate, so the owner-gated ping rejects the owner — bug #69).
- Test: owner pings their own box → 200; membership includes the owner.
- **Done:** owner can ping/act on their own box; 100% branch.

### B3 — Box-first trim (#85) · ~0.5–1 d · frontend · ∥ with B2
- The MVP shell shows **only the Box** (+ a minimal Settings for rename/recovery). Hide the legacy tabs — Dashboard, Connections, Terminal, Chat, Models — from the navigation (feature-flag/remove from the MVP shell; don't delete the code, it returns as plugins).
- Makes "lots broken" in the legacy surface **unreachable** — no need to fix it.
- **Done:** the app opens to the Box; no legacy tab is reachable; flutter analyze + tests green.

### B4 — Re-verify S8 on-device · ~0.5 d · Eddie's §14 gate · LAST (needs B1–B3)
- Rebuild on iPhone (**wired**, per #71's workaround) + iPad; run the full flow on the trimmed app:
  fresh install → **name device** → set password → save OMG code → create box → **share/copy** invite →
  **join** on the 2nd device → **ping** both ways → owner remove → wipe & **recover** (password + OMG).
- **Done:** Eddie signs off the flow works on both devices. This is MVP acceptance.

## Sequencing
B1 first → **B2 ∥ B3** (disjoint: backend membership vs frontend shell) → B4 (on-device, Eddie).

## Deferred — NOT this sprint (parked)
- **Cross-network** (cloud coordinator → Cloud Run; Eddie's GCP) — flips Box/ping off-LAN; the real-user gate.
- **bootc node** build/boot (`deploy/bootc/`) — authored; needs Eddie's subscribed env + Quay.
- **Real plugins** (LLM/Chat/Terminal/SSH/Squawk Box as actual plugins) — post-MVP.
- **#71** iPhone wireless deploy — a tooling workaround (USB), not a code item.
