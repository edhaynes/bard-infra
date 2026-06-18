# ADR-0007: React + Vite console for modeling device/user/application/workgroup relationships (additive to the Flutter client)

Date: 2026-06-08
Status: Proposed — **deferred to v2 (Walk); not MVP** (see `ROADMAP.md`)
Roadmap tier: v2 — Walk
Author: Jason-bard (PM / acting architect)
Relates to: ADR-0006 (trust front door), `TRUST_MODEL.md §3.1–§3.3`, features.md #45
Does NOT supersede: the Flutter end-user client (DESIGN.md §8g / reserved ADR-0005 / feature #40)

## Context

The refined trust model (`TRUST_MODEL.md §3.1–§3.3`) is a **graph**: organizations
contain visible/hidden workgroups; workgroups connect devices; devices carry
capability profiles (CPU/GPU/mem/net/storage) and run applications; users own
devices. Eddie 2026-06-08: *"we will use react and vite (if appropriate) to model
these relationships."*

Rendering and administering a topology/graph (browse org, see who's in which
workgroup, a device's capabilities, hidden vs visible) is awkward inside the
Flutter end-user tabs and natural in a web console.

## Decision

Introduce a **separate React + Vite web console** at `bardLLMPro/clients/console/`
for **modeling, visualizing, and administering** the relationships:
organizations · workgroups (visible/hidden) · devices (capability profiles) ·
users · applications · membership / approvals / revocation.

**Judgment on "(if appropriate)":** appropriate as an **additive admin/topology
surface**; **not** appropriate as a replacement for the Flutter client. The
Flutter app stays the cross-platform end-user client (iOS/Android/desktop, where a
web app is the wrong primary client and where the five-tab app is already built).
Two surfaces, **one shared contract** (`contracts/control-plane.openapi.yaml`) so
they cannot drift.

## Dependencies (flagged per CLAUDE.md hard rule #5 — sign-off before `npm install`)

| Dep | Purpose | License | ARM/native |
|-----|---------|---------|-----------|
| react, react-dom | UI | MIT | pure JS |
| vite, @vitejs/plugin-react | dev server + build | MIT | pure JS |
| typescript | types for the model | Apache-2.0 | pure JS |
| **(candidate, not added)** @xyflow/react (React Flow) | topology graph viz | MIT | pure JS — deferred until the stub proves the shape |

All ubiquitous, ARM-clean, no native build step. **The scaffold is committed as
files only; `npm install` is NOT run** until you approve the dep list.

## Consequences

- Two client codebases to maintain — mitigated by the shared control-plane
  contract and by clear scope (console = admin/topology; Flutter = end-user app).
- The console is desktop/web-oriented; it is not a mobile target.
- React Flow (or similar) likely needed for real topology viz — a future dep flag.

## Alternatives considered

- **Model relationships inside Flutter.** Rejected: graph/topology UX is weaker and
  it bloats the end-user app with admin concerns.
- **React replaces Flutter entirely.** Rejected unless Eddie explicitly directs —
  discards the built five-tab client and the ADR-0005 cross-platform rationale.
- **Defer the console.** Rejected: Eddie asked for stubs now.
