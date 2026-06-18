# Bard — Stranded Compute → Open Inference Pool
### One-page demo walkthrough (15 minutes, all real hardware)

**The claim.** Every enterprise already owns idle compute — the workstation GPU
that sleeps 20 hours a day, the dev laptop, the storage box, spare cloud quota.
Bard turns that **stranded compute** into a secure, schedulable
inference pool. No new hardware; capacity you already own and power. Built
native on Red Hat **UBI 9 + rootless Podman**, open end-to-end (llama.cpp, open
models), meshed over Tailscale/WireGuard.

**The live fleet** (no mockups — three real nodes, one shared agent image):

| Node | What it is | Capacity | Role |
|---|---|---|---|
| `mac-laptop` | Apple M5 Max (arm64) | 18 cpu · 48 GiB | Runs Registry + Router + console |
| `gx10-gb10` | NVIDIA GB10 workstation (arm64, Tailscale) | 20 cpu · 121 GiB | GPU-preferred worker — **real model** |
| `gcloud-run` | Google Cloud Run (amd64, scale-to-zero) | 1 cpu · 512 MiB | The "any cloud" beat — **$0 when idle** |

```
 Console (fleet map · pool · "Run inference")
    │ ② pool/schedule        ③ job (JWT)
    ▼                            ▼
 Registry ◄── ① register + heartbeat ──┐         ┌ Cloud Run ⑤
 (liveness, pool, placement)           │         │ scale-to-zero
    ▲                                  │         └ "any cloud"
 Router ──③ /infer (JWT, TLS)──► gx10 GB10 agent ④ rootless UBI9
                                  └─ llama.cpp → real answer ③
```

**The five beats:**

1. **Stranded compute** *(~3 min)* — the console (React, NOC-style fleet map)
   shows the heterogeneous nodes live: each UBI+Podman agent self-registered on
   boot, advertising its real CPU/RAM and capability profile, heartbeating;
   dead nodes go stale and leave the pool automatically.
2. **The pool** *(~2 min)* — one aggregate number: total idle CPU / GPU /
   memory across the fleet. Framing: **sustainability and democratization** —
   inference capacity without buying a single new GPU.
3. **A job lands** *(~4 min — the money shot)* — click "Run inference". The
   scheduler picks the best node (GPU-preferred, CPU-fallback = *any
   accelerator*), the GB10 lights up on the map, and a **real completion from
   an open model** streams back. `podman ps` on the workstation shows the
   rootless UBI container doing the work.
4. **Open & safe** *(~3 min)* — rootless Podman under the default `container_t`
   SELinux confinement (deny-by-default, MCS-isolated) on enforcing hosts,
   non-root, cap-drop, read-only rootfs, JWT on every hop, TLS-default. Honest
   framing: that's *default* container confinement today; *granular* per-workload
   SELinux policy with cgroup limits is the hardening roadmap — tighter than the
   generic domain, not confinement we lack.
5. **The Red Hat fit** *(~3 min)* — agents are plain Podman containers →
   Kubernetes/OpenShift resources; image distribution via Quay (+cosign/Clair);
   vLLM backend for real GPU throughput; complements RHEL AI / InstructLab.
   Prometheus `/metrics` already exposed on every service for fleet
   observability.

**What's real vs. roadmap (we say this out loud):** everything shown runs live —
registration, heartbeat liveness, pool aggregation, placement, real llama.cpp
inference in UBI containers, the scale-to-zero cloud node. Roadmap, presented
as such: GB10 **GPU** is advertised but inference is currently CPU (CUDA/vLLM
in progress); granular per-workload SELinux policy (default `container_t`
confinement is already in force on enforcing hosts); OpenShift scheduling; Valkey
HA control plane.

**Bring-up:** one command — `./scripts/demo_up.sh` (build, serve, agents,
console at `localhost:5173`); `demo_down.sh` tears down. Secrets are ephemeral
per run. Backup video recorded in case the live demo gods are unkind.
