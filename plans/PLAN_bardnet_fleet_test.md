Status: Not Implemented — authored 2026-07-01 (Jason-meta). Tier 1 (hermetic roster) is buildable today; Tier 2 (live) is gated on fleet bring-up.

# PLAN — Bardnet fleet onboard + ping test

> Goal (Eddie, 2026-07-01): a test that, **in succession, onboards every device in
> `shared-rules/connectivity.md`, then pings them all over bardnet.**
>
> **Naming:** the transport is **bardnet** — the renamed **LokNet** (feature #59;
> `PLAN_loknet.md`). "loknet" in code/tests/scripts is the retired internal codename;
> this plan uses **bardnet** throughout. (The loknet→bardnet symbol rename is a
> separate chore — tracked, not in scope here.)

## What already exists (do not rebuild)

- `scripts/smoke_box_demo.py` — the exact flow end-to-end (onboard → receive-link →
  ping fan-out, `SMOKE: PASS/FAIL`), but with **four fictional clients**
  (`dev-mac`, `dev-ios-sim`, `dev-linux-vm`, `dev-android-sim`), fully in-process
  (TestClient, no sockets).
- `tests/test_box_ping.py` — the frozen ping contract (fan-out to other members with
  live links; sender excluded; offline members listed not errored; auth/membership gates).
- `tests/test_loknet_register.py` — register-over-link (bardnet single front door).
- `scripts/smoke_broker.py` — real-socket (localhost WSS) mesh-free proof.
- `scripts/run_local_mac.sh` — one-command real-TLS 3-service fleet (Registry/Router/Agent).

This plan **parametrizes the existing flow with the real fleet roster** (Tier 1) and
**extends it to the physical boxes over real bardnet** (Tier 2). No new transport,
no new endpoints.

## The bardnet rails (grounded in code)

- **Onboard** = device generates an Ed25519 identity → redeems a single-use invite
  (`POST /invites` then `POST /invites/{token}/redeem`) → ACTIVE member of a box (channel).
- **Receive-link** = device opens WS `/v1/agent-link`, sends `{"type":"hello","agentId":<deviceId>,"authToken":<EdDSA JWT>}`, gets `hello_ok`; the Router keys a live link by `sub == deviceId`.
- **Ping** = a member calls `POST /channels/{box}/ping`; Router fans a `box.ping` frame to
  every OTHER member with a live link; members with no link are returned in `offline`
  (200, not an error); the sender is excluded.
- **Front door** = Router `uvicorn router.main:app` :8443 (public); Registry :8081 (private);
  Agent :8444, bardnet link via `BROKER_ENABLED=true`. Health `GET /healthz`, `GET /version`.

## The fleet roster (from `shared-rules/connectivity.md`, 2026-07-01)

| deviceId | box role | platform | reach | Tier-2 readiness |
|---|---|---|---|---|
| `dev-mac` (edwards-mbp) | member; also hosts Router+Registry | macOS arm64 | local | **READY** |
| `gx10` / `gladius` | member; also inference agent | Ubuntu 24.04 aarch64 | Tailnet `gladius` / LAN `10.0.0.97` | **READY** (on tailnet, has podman) |
| `bullfrog` | member; also inference agent | Ubuntu 26.04 x86_64 | LAN `10.0.0.36` (sshd up) | **PARTIAL** — not on Tailnet yet; LAN-only path works |
| `snoopy` | member | Debian aarch64 (BeaglePlay) | LAN `10.0.0.166` / ProxyJump via gx10 | **PARTIAL** — confirm Trixie+TI-kernel vs factory Bullseye; behind gx10 |
| `beagle` | member | Debian aarch64 (BeaglePlay) | behind gx10 | **BLOCKED** — DOWN (USB gadget failure) |
| `barney` | member | Debian aarch64 (BeaglePlay) | behind gx10 | **BLOCKED** — not powered |

> Half the fleet is not currently reachable. Tier 1 exercises **all six** regardless of
> box state (it's the fabric logic). Tier 2 onboards each box **as it comes up** and
> proves an unreachable box is correctly reported `offline` — that is a passing result,
> not a failure (the ping contract's offline-not-error branch is the point).

---

## Tier 1 — hermetic roster test (buildable today, CI-green)

**Deliverable:** the real roster drives the in-process onboard→link→ping flow; every
online device receives `box.ping`, deliberately-offline devices are listed `offline`.

- **T1.1** Add `tests/fleet_roster.py` — a single source of truth: the six devices above
  as `(device_id, label, platform, reachable_default)` tuples, imported by both the test
  and the demo script. *Done-signal: import resolves; `ruff` clean.*
- **T1.2** Add `tests/test_bardnet_fleet.py` (models `smoke_box_demo.py`'s in-process
  wiring; shared `DeviceStore`+`ChannelStore` across Registry+Router apps):
  - `test_onboard_all_devices_in_succession` — loop the roster, invite→redeem each, assert
    every one lands ACTIVE in `GET /channels/{box}/members`, **in roster order**.
  - `test_ping_fans_out_to_all_online` — every device opens a receive-link; one member
    pings; assert `delivered == roster \ {sender}` and every socket gets a `box.ping`.
  - `test_offline_boxes_listed_not_errored` — mark `beagle`/`barney` as no-link (their real
    state); assert `200`, they appear in `offline`, the rest in `delivered`.
  - `test_ping_before_onboard_is_403` — a roster device that hasn't redeemed can't ping.
  - *Done-signal: `uv run pytest tests/test_bardnet_fleet.py` green.*
- **T1.3** Extend `scripts/smoke_box_demo.py` (or add `scripts/smoke_bardnet_fleet.py`)
  to import the roster and print the narrated succession + fan-out with a final
  `SMOKE: PASS/FAIL`. *Done-signal: `uv run python scripts/smoke_bardnet_fleet.py` → PASS.*
- **T1.4** Wire into CI alongside `smoke_broker.py`; keep 100% line+branch (coding-rules §11).
  *Done-signal: full regression green, coverage ≥ prior.*

Sizing: T1.1–T1.4 are mechanical (parametrizing a proven flow) — each <1 file of real
logic, ≥90% first-try. **Estimate: ~1–2 hrs total** (record actual on completion per
the estimate→measure→calibrate rule).

---

## Tier 2 — live integration over real bardnet (gated on fleet bring-up)

**Deliverable:** the actual bardnet client runs **on each physical box**, connects over
real sockets to a real Router, and a real ping fans out across the real fleet.

**Clarified scope:** the ping rail needs a **bardnet receive-link client** on each box
(its device identity + `/v1/agent-link` link) — NOT necessarily the full LLM inference
agent. GPU boxes (gx10, bullfrog) may run the full agent (broker mode) as a superset;
the BeaglePlay boards run only the lightweight link client. Both register a live link the
same way, so both receive `box.ping`.

- **T2.1** Add `scripts/bardnet_node.py` — a minimal standalone client: load/generate the
  box's Ed25519 identity, redeem an invite (arg), open `/v1/agent-link`, hold the link,
  print received `box.ping` frames. Cross-platform (macOS/Linux/aarch64+x86). *Done-signal:
  runs on the Mac against a local Router and receives a ping.*
- **T2.2** Add `scripts/bardnet_fleet_live.py` (control-node driver, runs on the Mac):
  1. Start Router (:8443) + Registry (:8081) via `run_local_mac.sh` (or point at a deployed Router).
  2. Create the shared box with a fleet token; mint one invite per roster device.
  3. For each **reachable** box in succession: `ssh <box>` (per connectivity.md SOP —
     Tailnet name for gx10, LAN IP for bullfrog, ProxyJump via gx10 for the beagles),
     copy+launch `bardnet_node.py` with its invite, confirm `hello_ok`.
  4. Ping from one member; assert every reachable box logs `box.ping`; assert every
     unreachable box is in the ping response `offline` list.
  - *Done-signal: `delivered` = set of boxes actually brought up; `offline` = the rest;
    each live box's node log shows the frame.*
- **T2.3** Per-box readiness gates (the honest part — a box only joins when it's real):
  - **dev-mac** — ready now.
  - **gx10** — ready now (Tailnet `gladius`, podman present).
  - **bullfrog** — reachable over LAN `10.0.0.36`; onboard via LAN path. (Tailnet optional:
    `sudo tailscale up` at console per connectivity.md — not required for LAN onboarding.)
  - **snoopy** — confirm it booted the SD Trixie/TI-kernel image (not factory eMMC Bullseye)
    and install the gx10 key; reach via `ssh -J gx10 debian@10.0.0.166`.
  - **beagle / barney** — **park until powered/recovered** (USB-gadget/power fix in the
    beagleplay repo). Until then they are the deliberate `offline` cases in the assertion.
  - *Done-signal: each gate flips READY with a one-line proof (`ssh <box> hostname` +
    `bardnet_node.py` receives a ping).*
- **T2.4** Record proposed-vs-actual onboarding time per box (calibration); note any
  box-specific traps back into `connectivity.md`.

Sizing: T2.1 mechanical (~1 hr). T2.2 moderate — real SSH orchestration, split per-box
if it wobbles (§18.5). T2.3 is **externally blocked** (physical boxes), not code risk.

---

## Acceptance criteria

- **Tier 1:** `test_bardnet_fleet.py` + smoke script green in CI; all six roster devices
  onboard in succession; online→`delivered`, offline→`offline`; 100% line+branch held.
- **Tier 2:** every **currently-reachable** box (≥ dev-mac + gx10) onboards over real
  bardnet and receives a real `box.ping`; unreachable boxes are correctly reported
  `offline`; the run is repeatable via one driver command.
- **Both:** no hardcoded secrets (ephemeral per-run, per `smoke_box_demo.py`); secret
  scan clean; diffs shown before commit.

## Out of scope

Full inference dispatch (`/infer`) across the fleet; the loknet→bardnet symbol rename;
Skupper/Profile-B transport; multi-box HA; BeaglePlay hardware recovery (beagleplay repo).
