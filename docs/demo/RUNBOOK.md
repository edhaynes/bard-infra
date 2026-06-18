# Demo Runbook — "Stranded Compute → Open Inference Pool" (Chris Wright)

Status: **Working end-to-end on real hardware** (2026-06-09). A real 2-node UBI+Podman
fleet over Tailscale, live dashboard, real model inference landing on the NVIDIA GB10.

## What it is
An open fabric that turns an enterprise's **stranded compute** — idle CPU/GPU across the
fleet — into a secure, schedulable pool. Inference is the first workload. Built native on
Red Hat **UBI + rootless Podman**, meshed over **Tailscale** (the product's #43 transport).

## The real fleet
| Node | Host | Arch | Capacity | GPU | Role |
|---|---|---|---|---|---|
| `mac-laptop` | this Mac | arm64 | 18 cpu · 48 GiB | Apple M5 Max | CPU worker + fleet/pool |
| `gx10-gb10` | gx10 (Tailscale `100.97.246.73`) | arm64 | 20 cpu · 121 GiB | **NVIDIA GB10** | GPU-preferred worker (real model) |
| `gcloud-run` | Google Cloud Run (`us-central1`) | amd64 | 1 cpu · 512 MiB | — | **scale-to-zero** cloud node (echo; the "any cloud" beat) |

Both run the same UBI9 agent image (`bardpro-agent:demo`), self-register over Tailscale
(plain HTTP — WireGuard already encrypts the hop; requires the explicit
`BARDPRO_ALLOW_INSECURE_HTTP=true` opt-in, and the agent logs a startup WARNING),
and advertise a capability profile.

## Architecture (what's happening — numbers match the five beats)

```
                EDDIE'S MAC — M5 Max (arm64)
 ┌──────────────────────────────────────────────────────────┐
 │  Demo console  (React/Vite, localhost:5173)              │
 │  fleet map · pool KPIs · "Run inference" button          │
 │     │ ②  GET /agents · /pool        ③ POST /v1/message   │
 │     │     GET /schedule?gpu=true       (JWT)             │
 │     ▼                                                    │
 │  ┌─────────────┐  resolve targetAgent  ┌──────────────┐  │
 │  │ Router      │──────────────────────►│ Registry     │  │
 │  │ :9443       │                       │ :8081        │  │
 │  │ JWT gate    │                       │ pool·schedule│  │
 │  └──────┬──────┘                       │ liveness/TTL │  │
 │         │                              └──────▲───────┘  │
 └─────────┼─────────────────────────────────────┼──────────┘
           │ ③ forward /infer                    │ ① register +
           │   (JWT on every hop)                │   heartbeat (15s)
           ▼          Tailscale / WireGuard      │   + capability profile
 ┌──────────────────────┐  (encrypted hop)  ┌────┴─────────────────┐
 │ gx10 — NVIDIA GB10   │◄──────────────────│ every agent dials in │
 │ 20 cpu · 121 GiB     │                   └──────────────────────┘
 │ UBI9 · rootless      │      ┌───────────────────────────────┐
 │ Podman · non-root ④  │      │ Cloud Run — "any cloud" ⑤     │
 │ llama.cpp → real     │      │ scale-to-zero · echo agent    │
 │ model answers ③      │      │ public URL · JWT-gated        │
 └──────────────────────┘      │ registered by the Mac         │
                               └───────────────────────────────┘

 ① Stranded compute announces itself — each UBI+Podman agent self-
    registers with its capability profile and heartbeats; dead nodes go
    stale and leave the pool automatically.
 ② The pool — Registry aggregates live capacity; the console renders it.
 ③ A job lands — console → Router (JWT) → /schedule picks the GB10
    (GPU-preferred, CPU-fallback) → /infer → a real llama.cpp answer
    returns up the same path.
 ④ Open & safe — rootless UBI9 Podman, non-root user, cap-drop,
    read-only rootfs, JWT on every hop, TLS-default transport.
 ⑤ Red Hat fit / any-cloud — the same agent image runs on-prem or
    serverless; Prometheus /metrics on every service.
```

## Architecture (what's running)
- **Registry + Router** on the Mac (`scripts/demo_serve.py`, plain-HTTP + CORS, bound
  `0.0.0.0`): Registry `:8081`, Router `:9443` (8443 is taken by Tailscale's IPNExtension).
- **Agents** = UBI+Podman containers on each node; self-register on boot with their profile.
- **Registry `/pool`** aggregates advertised capacity; **`/schedule?gpu=true`** picks the
  best node (GPU-preferred, CPU-fallback). **Router `/v1/message`** forwards a job to the
  chosen agent → llama.cpp completion.
- **Dashboard** = `clients/demo-console` (React/Vite, cdn-sim theme): fleet view + pool KPIs
  + "Run inference" → schedule → node lights up → real answer. Reads `/agents`, `/pool`,
  `/schedule`, `/v1/message` via `.env.local` (written by the bring-up).

## Run it
```sh
cd bardLLMPro
./scripts/demo_up.sh        # build images (Mac+gx10), serve-mode, agents, dashboard
# → open http://localhost:5173 and click "Run inference (GPU-preferred)"
./scripts/demo_down.sh      # tear down
```
Env overrides: `BARDPRO_GX10_SSH`, `BARDPRO_GX10_IP`, `BARDPRO_MAC_TS_IP`,
`BARDPRO_GX10_BACKEND` (`llamacpp` real model / `echo` fast).

## The cloud node (scale-to-zero, "any cloud")
A serverless agent on **Google Cloud Run** — **$0 when idle**, cold-starts on a request.
Built UBI+Podman (`agent/Containerfile.cloud`, slim/echo, no llama), pushed to Artifact
Registry, deployed scale-to-zero. The JWT secret lives in **Secret Manager** (not a plain
env var); the service is public but **JWT-gated** (echo-only, ephemeral secret). The Mac
registers it (its public URL) since Cloud Run can't reach the on-prem Tailscale registry.
```sh
# build (podman, amd64) + push
podman build --platform linux/amd64 -f agent/Containerfile.cloud \
  -t us-central1-docker.pkg.dev/<project>/bardpro/bardpro-agent-cloud:demo .
podman login -u oauth2accesstoken -p "$(gcloud auth print-access-token)" us-central1-docker.pkg.dev
podman push us-central1-docker.pkg.dev/<project>/bardpro/bardpro-agent-cloud:demo
# secret → Secret Manager, deploy scale-to-zero
printf '%s' "$SECRET" | gcloud secrets create bardpro-jwt-secret --data-file=-
gcloud run deploy bardpro-cloud-node --image=<AR>:demo --region=us-central1 \
  --allow-unauthenticated --min-instances=0 --max-instances=2 \
  --set-secrets=BARDPRO_JWT_SECRET=bardpro-jwt-secret:latest \
  --set-env-vars=BARDPRO_AGENT_ID=gcloud-run,BARDPRO_INFERENCE_BACKEND=echo
# register from the Mac: POST /register {agentId:gcloud-run, address:<Cloud Run URL>, ...}
# teardown: gcloud run services delete bardpro-cloud-node --region=us-central1
```

## The 15-minute story (5 beats)
1. **Stranded compute** — the dashboard shows real heterogeneous nodes (M5 Max + GB10),
   idle capacity, rootless UBI+Podman.
2. **The pool** — aggregate idle CPU/GPU/memory. *No new hardware — capacity you already own.*
3. **A job lands** — "Run inference" → `/schedule` picks the GB10 → real model answer.
   (`podman ps` on gx10 shows the real UBI container.)
4. **Open & safe** — open end-to-end (UBI, Podman, llama.cpp, open models), over Tailscale.
   On an enforcing host the agents inherit Podman's **default `container_t` SELinux
   confinement** (deny-by-default, MCS-isolated), plus non-root user, `--cap-drop=all`,
   `no-new-privileges`, read-only rootfs, pids-limit. The *granular* per-workload
   SELinux policy (#48) is the hardening roadmap — tighter than the default domain,
   not confinement we lack. (SELinux applies on the Linux nodes; the Mac control
   node has none.)
5. **Red Hat fit** — OpenShift path (Podman → kube, #52), Quay distribution (#53),
   complements RHEL AI / InstructLab; GPU acceleration via vLLM (#51).

## Honest limitations (do not overclaim)
- **GPU is advertised, not yet harnessed.** gx10 runs llama.cpp **CPU** (20 ARM cores);
  the GB10 GPU is capability-advertised. Real GPU inference = CUDA llama.cpp / vLLM (#51) —
  in progress.
- **Mac is fleet/pool only**, not a job target: the Linux container can't reach Apple Metal
  (no macOS GPU passthrough) and isn't router-reachable. A "Mac as worker" needs the native
  Metal path. Jobs land on gx10.
- **Container confinement = Podman default `container_t` + baseline hardening**
  (non-root `bard` user, all capabilities dropped, `no-new-privileges`, read-only
  rootfs + tmpfs `/tmp`, pids-limit; sshd installed for v2 but never started). On an
  SELinux-enforcing host that default domain is already deny-by-default with MCS
  isolation; what's roadmap is the *granular* per-workload SELinux policy (#48) —
  not "no SELinux today." On a non-enforcing host (e.g. the Mac), SELinux does not apply.
- Secrets/tokens are ephemeral (regenerated per `demo_up.sh` run); never committed.
