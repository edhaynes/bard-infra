# Brief for Claude design — 10-slide deck, Chris Wright (Red Hat CTO)

Status: Brief for generation. Source of truth = `RUNBOOK.md` + `ONE_PAGER.md`
(this deck must not claim anything those two don't). 2026-06-10.

## Audience (read this first)
One reader: **Chris Wright, Red Hat CTO.** Former Linux kernel hacker, **LSM
maintainer — SELinux is literally his code**. He is not a marketing audience and
will distrust a marketing deck. He thinks in terms of upstream-first, "default to
open," "any model / any accelerator / any cloud," and inference as the production
runtime. He can spot a hand-wave from the back of the room.

## Voice — the whole point of this brief
**Reserved, precise, engineer-to-engineer.** This is a senior architect showing a
working thing to a CTO, not a vendor pitching. Concretely:

- **Do:** short declarative sentences. Real numbers (2 real nodes, 20-core GB10,
  100% test coverage, $0-idle Cloud Run). Name the open components by name (UBI9,
  rootless Podman, llama.cpp, OpenMLS). State limitations before he asks.
- **Do:** let the architecture carry the weight — one clear diagram beats three
  adjectives. Assume he understands NAT, JWT, SELinux, scheduling without a primer.
- **Don't:** superlatives ("revolutionary," "game-changing," "seamless,"
  "unleash," "supercharge"). No exclamation points. No "enterprise-grade" /
  "next-generation" filler. No stock-photo futurism. No claim the code can't back.
- **Don't:** explain Red Hat's own strategy back to him. Reference RHEL AI /
  InstructLab / OpenShift as *integration surfaces*, not as flattery.
- **Tone test:** if a sentence would feel out of place in a pull-request
  description or an architecture review, cut it.

## Design constraints
- 10 slides. Heavy whitespace, one idea per slide, ≤ ~25 words of body text per
  slide. Monospace for anything that is code/host/port/command.
- Restrained palette — Red Hat red as a single accent, not a wash. Diagrams in
  neutral ink. No gradients-for-their-own-sake.
- Reuse the ASCII architecture diagram from `RUNBOOK.md` as the basis for the
  rendered diagram on slides 4 and 5 (numbers ①–⑤ map to the beats).
- Every slide gets a **speaker note** (what Ed says) separate from the on-slide
  text. The slide is the evidence; the note is the narration.

## Honesty guardrails (do not cross — he will catch it)
- **SELinux — get this exactly right; he wrote the subsystem.** On an
  SELinux-enforcing host (RHEL/UBI), the agents **inherit Podman's default
  `container_t` confinement today** — deny-by-default, with MCS category isolation
  between containers. That IS real, shipped confinement; say it plainly. What's
  **roadmap is *granular*, per-workload SELinux policy** (custom domain/types,
  per-task grants — feature #48), i.e. *tighter than the generic `container_t`
  domain*, not "confinement we don't have yet." Frame it as "default confinement
  today, granular policy next" — NOT "SELinux is roadmap." One honest caveat:
  SELinux applies only where the host enforces it (the Linux nodes); the demo's
  Mac control node has no SELinux — don't imply blanket coverage.
- GPU is **advertised, scheduled-to, capability-matched** — but the live model run
  is **CPU llama.cpp** on the GB10's 20 ARM cores today; CUDA/vLLM is in progress.
  Say so on the limitations slide.
- Zero-trust identity / post-quantum / MLS group keying are **roadmap (v3)**, with
  the JWT-behind-a-swappable-verifier seam already in the code. "Designed-for, not
  done." Never imply the PQ fabric exists today.

---

## The 10 slides

**1 — Title.**
On-slide: "Stranded compute → an open inference pool." Subline: a working MVP.
One line of provenance (Ed Haynes, Senior Solutions Architect). No tagline.
Note: 10-second framing — "a working prototype, 15 minutes, mostly a live demo."

**2 — The problem, stated flatly.**
On-slide: every org already owns idle compute — workstation GPUs, dev laptops,
spare cloud quota — sitting dark most of the day. One honest stat or a simple
utilization sketch. No fear-selling.
Note: this is a utilization and sustainability problem, not a buy-more-GPUs problem.

**3 — The idea in one sentence.**
On-slide: pool that stranded capacity behind one authenticated endpoint; inference
is the first workload. "Any model, any accelerator, any cloud — on hardware you
already own." (His own thesis, stated as our design goal, not quoted back at him.)
Note: open end-to-end is a constraint we accepted, not a feature we added.

**4 — Architecture (the spine).**
On-slide: the rendered fleet diagram — Console → Router (JWT) → Registry
(liveness/pool/placement) → UBI+Podman agents (llama.cpp). Frozen JSON contracts.
Note: walk the request path once, calmly. This is the whole system; it fits in one
diagram on purpose — "one engineer can hold it in their head."

**5 — What's actually running (live-demo slide).**
On-slide: the real fleet table — M5 Max Mac, NVIDIA GB10 (20 cpu/121 GiB), Cloud
Run ($0 idle). "This is live, not a render." The five beats ①–⑤ as a strip.
Note: cue to switch to the live console; if the live demo fails, the backup video.

**6 — Open & safe, honestly.**
On-slide: two columns. *Today:* rootless Podman under the default `container_t`
SELinux confinement (deny-by-default, MCS-isolated) on enforcing hosts, non-root,
cap-drop, read-only rootfs, JWT every hop, TLS-default. *Roadmap:* granular
per-workload SELinux policy (+cgroup limits, feature #48), zero-trust identity,
PQ/MLS. The line between them is visible and deliberate.
Note: precision over polish here — "default container confinement today, granular
per-workload policy next; SELinux where the host enforces it." To the person who
maintains LSM, getting the boundary exactly right IS the credibility — don't round
it up to "default-deny everywhere," don't round it down to "SELinux is roadmap."

**7 — Any cloud, any accelerator.**
On-slide: the same agent image runs on-prem (GB10) and serverless (Cloud Run,
scale-to-zero). Capability-aware placement: GPU-preferred, CPU-fallback. One honest
caveat chip: "GPU advertised; live run is CPU today — CUDA/vLLM in progress."
Note: "any accelerator" is a scheduling property, demonstrated, with the GPU
harness as the next step — don't oversell it.

**8 — Where it meets Red Hat.**
On-slide: integration surfaces, not flattery — Podman → Kubernetes/OpenShift
resources; images via Quay (cosign/Clair); complements RHEL AI / InstructLab;
vLLM for GPU throughput. Listed as plug-points.
Note: frame as "this composes with the stack you already own," one sentence each.

**9 — The ask.**
On-slide: one specific ask (not "thoughts?"). e.g. a follow-up with the AI platform
team, or a pointer to the right upstream community. Contact line.
Note: keep it small and concrete; leave the one-pager as the leave-behind. Then turn
to the closing slide — "here's where it goes."

**10 — Roadmap, tiered (the closer).**
On-slide: crawl/walk/run in three short columns. v1 (shipped: this MVP) · v2
(LokNet mesh-free transport, console, Valkey) · v3 (zero-trust PQ + MLS fabric).
Honest about what is shipped vs designed. End the deck on the direction, not a
thank-you slide.
Note: the trust model is real design work, deliberately deferred — show the
direction, don't claim the destination. Last words land on where this is headed and
the one concrete next step from slide 9, so he leaves looking at the trajectory.

---

## Deliverable
10 slides + speaker notes. A 16:9 deck and the speaker notes as a separate page.
Keep a text outline alongside the rendered deck so edits don't require regenerating
art. If any slide can't be honest within these guardrails, leave it as an outline
and flag it rather than inventing a claim.
