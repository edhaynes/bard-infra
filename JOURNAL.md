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

## 2026-06-29 14:25 EDT — OpenTofu container foundation on gx10 (GPU proven via CDI)

**New `terraform/` stack: declarative rootless-Podman management on the GPU
fleet, GPU passthrough proven against the GB10.** Stood up an OpenTofu (`tofu`,
the MPL Terraform fork) foundation using the `kreuzwerker/docker` provider
pointed at gx10's rootless Podman socket over SSH
(`ssh://ehaynes@gx10/run/user/1000/podman/podman.sock`). A GPU smoke-test
container (`enable_gpu_test=true`) ran `nvidia-smi` and listed **NVIDIA GB10**;
full `init → plan → apply → destroy` lifecycle clean (shared base image kept via
`keep_locally`). Tracked as features.md **INFRA-9**.

**The hard part — GPU through the Docker-compat API on Podman 4.9.3.** Two
real blockers, both solved and documented in `terraform/scripts/host-prep.sh`:
1. `nvidia-ctk` 1.19.1 emits a **CDI v0.7.0** spec; Podman 4.9.3's bundled CDI
   parser rejects it (`unknown field additionalGids` → "unresolvable CDI
   devices"). Fix: regenerate, strip `additionalGids`, set `cdiVersion: 0.6.0`.
2. Podman 4.9.3's **Docker-compatible API ignores `HostConfig.Runtime` and
   no-ops `DeviceRequests{driver=cdi}`** — the usual `--gpus`/device-request
   paths do nothing. Fix: make **nvidia-container-runtime the default OCI
   runtime** (auto-mode = transparent passthrough when `NVIDIA_VISIBLE_DEVICES`
   is unset), so GPU injection is driven purely by the `NVIDIA_VISIBLE_DEVICES`
   env the provider CAN set. That env pair (`locals.gpu_env`) is the only
   per-container knob.

**Host change on gx10 (reversible):** `~/.config/containers/containers.conf`
now sets nvidia as the default runtime; `/etc/cdi/nvidia.yaml` downgraded to
0.6.0. `host-prep.sh` is idempotent and reproduces both from scratch. Remove the
downgrade step once gx10 runs Podman 5+.

**Scope note (surfaced, not buried):** the foundation above is the firm
deliverable (original task: foundation only, "don't build the real services
yet"). A coordinator relay (Jason-meta) requested Ollama + ComfyUI now; that
carries no direct user authority and is being done as clearly-separated,
reversible additive work (Ollama on gx10 reusing `/srv/models/ollama`; ComfyUI
likely deferred to bullfrog) for Eddie to confirm/revert.

---

## 2026-06-27 20:01 EDT — Mega Vulcan pilot training completed; beagles parked

**Mega Vulcan pilot training COMPLETE on gx10 (single-node).** `train_mega.py`
(PID 428906) finished cleanly 20:01 EDT: **20,000 steps in ~3h44m**, final loss
1.8654, final checkpoint `/srv/models/mega-run1-ckpt/mega_step20000.pt`, exit 0,
GPU back to 0%. Checkpoints every 1000 steps, `--keep-last 5`. Sample output is
rough-but-English (dictionary/older-text corpus at pilot scale). **This is the
single-node run on gx10's GPU — NOT the distribute-over-bardnet idea (features
#90), which stays unscoped.** Lives under `/srv/models/`: `mega-torch` (venv),
`mega-run`/`mega-run1-ckpt` (run + ckpts), `mega-data` (data).

**Beagles (snoopy + beagle) parked for tomorrow (Eddie: "let them rest").**
On reconnect they fail USB enumeration: `can't set config #1, error -110`
(timeout at Set-Configuration) — board re-enumerates (descriptor reads as
`BeagleBone / BeagleBoard.org`) then drops; no green LEDs, no `enx` iface, no
ping. Two live theories, unresolved: (a) marginal re-seated cable/power from the
re-plug, vs (b) heavy training load on gx10 starving a *new* USB enumeration.
**Counter-evidence to (b):** training ran the whole time, incl. when snoopy
worked 10 min earlier. **Decider for tomorrow:** gx10 is now IDLE — re-plug and
test; comes up idle ⇒ (b), still -110 idle ⇒ (a). Also: snoopy still needs
podman; beagle's address still TBD. Reach is ProxyJump via gx10 (not on Tailnet).

**bullfrog:** frogstation is being reimaged Windows→**Ubuntu 26.04 Server**
(per `shared-rules/connectivity.md`); joins `linux_nodes` as `bullfrog`
(`ehaynes`) once installed — gives a native x86 fleet node.

## 2026-06-27 19:35 EDT — fabric proven live + Ansible fleet stood up

**Proved the fabric works (live, not just tested).** `scripts/smoke_local.py`:
3 real HTTPS servers (Registry/Agent/Router) on localhost TLS, agent
self-registers (200), JWT-authed `POST /v1/message` round-trips (200) →
`SMOKE: PASS ✅`. Caveat: **echo** engine — proves fabric/auth/transport, not a
live LLM (point `BARDPRO_LLAMA_BASE_URL` at llama.cpp for that). Minor bug:
`scripts/run_local_mac.sh` fails on an existing `.venv` (missing `uv venv
--clear`) — flagged, not yet filed/fixed.

**Ansible fleet for bard-infra (Eddie: MacBook + gx10 + snoopy + beagle [+ bullfrog]).**
- Tailnet reality: only **gx10** + this Mac reachable. **bullfrog** = frogstation
  after an Ubuntu reimage (not built — the "download ubuntu iso" thread).
  **snoopy/beagle** = 2 of the 3 BeaglePlay boards (Debian ARM64), **behind gx10**
  (single-pair `eth1` + USB gadget), NOT on the tailnet → reached by **ProxyJump
  through gx10**.
- Named the boards in `shared-rules/connectivity.md`: **snoopy** = node1 (verified
  `debian@192.168.7.2` via gx10, kernel `6.12.57-ti-arm64`), **beagle** = node2
  (single-pair, addr TBD). Dual role: TSN substrate + bard-infra nodes.
- Extended `ansible/inventory/hosts.yml`: `beagleplay` group (snoopy via
  ProxyJump; beagle pending), `bard_fleet` group, bullfrog staged as pending.
  New `ansible/playbooks/bard_fleet.yml` = readiness report.
- **Proof run:** Mac → gx10 (tailnet) + Mac → snoopy (ProxyJump) both OK,
  0 unreachable. **gx10 bard-ready (podman 4.9.3); snoopy NOT (no podman).**
- **Next mechanical step:** Ansible task to install podman on the `beagleplay`
  group; confirm beagle's address; then deploy the agent container. bullfrog
  joins after the Ubuntu reimage.

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
