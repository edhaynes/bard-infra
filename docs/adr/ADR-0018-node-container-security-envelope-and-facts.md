# ADR-0018: The node container as security envelope; facts by default, resources on enable

Date: 2026-07-01
Status: **Accepted** 2026-07-01 (Eddie — "everything through the container … smallest footprint … Option A")
Relates to: ADR-0013 (outbound agent broker), ADR-0014 (two deployment profiles), features #91 (management screen / fleet console), #64/#65 (console + per-device/workgroup enable), #60 (storage discovery), `plans/PLAN_fleet_facts_console.md`.

## Context

The fleet console (#91) needs each node's real hardware facts — CPU, memory, GPU,
storage, networking — rendered as a node tree. Two questions had to be settled
before building: **where do facts come from**, and **what security posture does a
node run in**.

Eddie's rulings, in order (2026-07-01):

1. Do **not** hand-roll a fact gatherer in the agent — **leverage open-source
   ansible** (`setup` is a battle-tested, cross-platform collector).
2. **Each node runs one lightweight podman container.** It gathers facts by
   default (**read-only**); if the owner enables it (per device or per
   workgroup) it may **read/write and serve resources**. First resource = **LLM
   inference** (bard-llm / llama.cpp).
3. **Everything goes through the container, for security. Smallest footprint
   possible.**

Constraints (2) + (3) pull against (1): ansible's collector is Python + ansible-core
(tens of MB), which fights "smallest footprint." Three reconciliations were weighed
(see the plan doc's table): **A** — node container stays minimal and is the security
envelope, ansible drives `setup` *through* it; **B** — ansible runs *inside* every
node container (self-contained but heavy); **C** — two images (tiny facts + heavier
inference). Eddie chose **A**.

## Decision

1. **The node container is the sole security boundary on each node.** Nothing on
   the node is reachable except through this one hardened podman container
   (already the demo posture: `--cap-drop=all --security-opt=no-new-privileges
   --read-only --tmpfs /tmp --pids-limit`). Facts, inference, and every future
   resource flow through it; there is no side-channel to the host.

2. **Two postures, one control plane:**
   - **Default = read-only facts.** The container reports the node's hardware
     facts and nothing else. No writable mounts, no host resources committed.
   - **Owner-enabled = read/write + resources.** Per **device or workgroup**, the
     owner turns on resource serving. **First resource = LLM inference**
     (`agent/engine.py`, llama.cpp OpenAI-compatible). This **inverts today's
     default** (the container currently serves inference by default) — inference
     weight and host resources (`--gpus`, writable model dir) land **only on
     enable**.

3. **The enable toggle rides the existing per-device/workgroup capability seam
   (#65 plugin manager), not a new control surface.** Default capability set =
   `facts:read`; enabling adds `inference` (and later other resources). One gate,
   reused.

4. **Facts source = ansible `setup`, driven *through* the node container
   (Option A).** The control plane targets the node **container** (podman/ssh
   connection plugin), not a side-channel SSH-to-host — honouring "everything
   through the container." GPU (which `setup` does not cover) is filled by a
   supplemental `nvidia-smi` task cached alongside. Facts land in ansible's
   jsonfile cache; the control-plane projector (`registry/node_facts.py`) maps
   them to the frozen `NodeFacts` contract and serves `GET /nodes`.

5. **Facts are the HOST's truth, read-only.** A cgroup-limited container would
   otherwise report *its* view (2 CPU / 2 GB), not the node's real hardware. The
   facts posture is granted **narrow read-only host introspection** (host `/proc`
   + `/sys` read-only, host network namespace) and nothing writable. This is the
   one place the envelope sees the host, and it sees it read-only.

## Consequences

- **Honest footprint note.** Option A still needs a Python interpreter in the
  node container so ansible can execute its modules there — "minimal" means
  UBI-minimal + python + ansible-core, **not** a zero-Python static binary. That
  is the accepted cost of choosing ansible (Eddie's call) over a hand-rolled
  static collector. Inference weight (llama-server + libs) is **not** in the
  default image path — it arrives only on enable.
- **Downstream is unaffected by the gather transport.** The projector reads
  whatever ansible cached; the console renders `NodeFacts` — neither depends on
  SSH-to-host vs container-target. So S2 (projector), S3 (`/nodes`), S4
  (console tree) proceed against the frozen contract now; the container/connection
  wiring is S1/S5 work.
- **#60 storage discovery resolved by facts, not by extending the power
  profile.** `power-profile.schema.yaml` stays a resource *ceiling*; real
  storage/cpu/mem/gpu/net come from facts.
- **Security win:** default posture commits zero host resources and exposes zero
  writable surface — a node that never gets enabled is a pure read-only reporter.
- **Follow-ups:** the exact podman connection + host-introspection flags need
  empirical validation on gx10/snoopy (measure, §11.1); AMD/Intel GPU probes;
  Windows/WinRM facts (deferred — Linux fleet first, frogstation→bullfrog is
  moving to Linux anyway).

## Alternatives considered

- **B — ansible inside every node container (self-contained).** Rejected:
  Python+ansible-core in every node's *default* image violates "smallest
  footprint," and offline self-gathering isn't required (the control plane is
  always the consumer).
- **C — two images (tiny static facts collector + heavier inference).** Rejected
  for now: a static collector abandons "leverage ansible," and two image
  lifecycles cost more than the single minimal-envelope model. Revisit if the
  Python-in-target footprint proves unacceptable on the smallest boards.
- **Home-grown psutil/nvidia-smi gatherer in the agent.** Rejected by ruling (1).

## Amendment 2026-07-01 (same day) — base image for the minimal facts posture

Eddie: "use ubi or even … project hummingbird from Red Hat." Recorded here as a
same-day amendment (not a silent post-acceptance edit — this closes the open
footprint question raised in the Consequences).

**Decision:** the minimal **facts posture** targets a **Red Hat distroless
Python** base — **Project Hummingbird** (Red Hat's hardened, near-"zero-CVE",
SBOM-carrying minimal images; a Python runtime image exists; freely
redistributable like UBI, so commercial-license-clean per our permissive-only
rule) — with **`ubi-micro`/`ubi-minimal` as the fallback** if Hummingbird
early-access isn't available for a given arch/board. The heavier **inference
posture** keeps the existing UBI-9 image (`agent/Containerfile`).

**Why it fits:** Option A needs a Python interpreter in the target (for ansible
modules); Hummingbird's distroless Python gives that at the smallest hardened
footprint, satisfying "smallest footprint" + "everything through the container"
+ Red Hat alignment simultaneously.

**Honest caveats (distroless ⇒ no shell / no package manager / no external
binaries):**
- ansible `setup` facts that **shell out** (a few) degrade to what's readable
  from `/proc`+`/sys` in pure Python — which still covers our core
  cpu/mem/storage/networking. Validate the exact fact coverage on the image
  (§11.1, measure — don't assume).
- The **`nvidia-smi` GPU probe cannot run in a pure distroless image** (no
  binary). GPU facts therefore come from the **enabled/inference posture** (GPU
  nodes are enabled to serve inference anyway, and that image can carry the
  driver tooling), OR a narrowly-added probe. Non-GPU nodes are unaffected
  (`bard_gpu` = `[]` ⇒ `gpu: null`).
- **Availability:** Hummingbird is early-access / subscription-gated at time of
  writing — hence the `ubi-micro` fallback so the build never blocks on it.

This does not change S2–S4 (base image is S1/S5 container work).
