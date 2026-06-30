# bard-infra · terraform/

OpenTofu foundation for managing **rootless Podman containers on the GPU fleet**.
This is the substrate real Bard services snap onto. It manages two first-class
hosts, each via its own variable-driven `docker` provider:

| Host | Provider | Arch / GPU | Podman | Role |
|---|---|---|---|---|
| **gx10** | default `docker` | aarch64 / GB10 (128 GB unified) | 4.9.3 | training + Ollama |
| **bullfrog** | `docker.bullfrog` alias | x86_64 / RTX 5080 (16 GB) | 5.7.0 | **inference / serving** (Ollama; ComfyUI staged) |

No host literal is baked into resources — both hosts' coordinates flow from
`variables.tf` / `locals.tf`, and each host's services are toggled by its own
`enable_*` flags.

> Uses **OpenTofu** (the OSS, MPL-licensed Terraform fork — `tofu` CLI, standard
> `.tf` files). Do **not** use HashiCorp Terraform (BSL).

## What this is

- A `kreuzwerker/docker` provider pointed at gx10's **rootless Podman socket over
  SSH** (`ssh://ehaynes@gx10/run/user/1000/podman/podman.sock`).
- A GPU smoke-test resource (`enable_gpu_test`) that runs `nvidia-smi` inside a
  container and proves the GB10 is visible through the provider via **CDI**.

The host part of GPU passthrough is **not** in Terraform (it's host config, not a
container) — it lives in `scripts/host-prep.sh`, run once per host.

## Prerequisites

| Where | Need |
|---|---|
| Your Mac/laptop | `tofu` (`brew install opentofu`); SSH access to the host (`ssh gx10` must work passwordlessly — see `../connectivity.md`) |
| The Podman host | Rootless Podman with its API socket active (`/run/user/<uid>/podman/podman.sock`); NVIDIA driver + `nvidia-ctk`; **`scripts/host-prep.sh` run once** |

### One-time host prep (GPU enablement)

Run on the host (needs passwordless sudo for the CDI step):

```bash
ssh gx10 'bash -s' < scripts/host-prep.sh
```

This (1) generates the NVIDIA **CDI** spec at `/etc/cdi/nvidia.yaml`, (2)
downgrades it to CDI v0.6.0 (Podman 4.9.3's parser rejects the v0.7.0 spec
`nvidia-ctk` emits by default), and (3) sets **nvidia-container-runtime as
Podman's default OCI runtime** so GPU injection is driven by the
`NVIDIA_VISIBLE_DEVICES` env var alone. See the script header for the full
rationale. The runtime runs in auto/passthrough mode — non-GPU containers are
unaffected.

Confirm the device exists:

```bash
ssh gx10 'nvidia-ctk cdi list'   # expect: nvidia.com/gpu=all (+ per-GPU entries)
```

## Usage

```bash
cd terraform
tofu init                                   # installs the provider, writes the lock file
tofu plan  -var enable_gpu_test=true        # preview (connects to gx10 over SSH)
tofu apply -var enable_gpu_test=true        # create the GPU test container
ssh gx10 podman logs bard-gpu-test          # <-- should list "NVIDIA GB10"
tofu destroy -var enable_gpu_test=true      # tear the test down (base image kept)
```

With no vars, `tofu apply` manages an empty stack against gx10 (the GPU test is
opt-in). Copy `terraform.tfvars.example` → `terraform.tfvars` to override hosts;
the real `terraform.tfvars` is gitignored.

## How GPU passthrough works (the working incantation)

Discovered against **Podman 4.9.3 + nvidia-ctk 1.19.1** on the GB10:

- Podman 4.9.3's **Docker-compatible API** (what the provider speaks) **ignores**
  `HostConfig.Runtime` and **no-ops** `DeviceRequests{driver=cdi}` — so the usual
  Docker `--gpus` / device-request paths do nothing here.
- The path that *works through the provider*: nvidia-container-runtime is the
  host's **default** runtime, and the container sets
  **`NVIDIA_VISIBLE_DEVICES=all`** (+ `NVIDIA_DRIVER_CAPABILITIES=all`). The
  runtime then CDI-injects the GPU. That env pair is the only per-container knob
  (`locals.gpu_env`); set it on any container that needs the GPU.

## Files

| File | Purpose |
|---|---|
| `versions.tf` | OpenTofu + provider version constraints |
| `providers.tf` | `docker` provider → remote rootless Podman over SSH |
| `variables.tf` | All tunables (host, socket, GPU, test toggle) |
| `locals.tf` | Builds the `ssh://` host URL and the GPU env from variables |
| `gpu_test.tf` / `gpu_test_bullfrog.tf` | Opt-in GPU smoke-test (gx10 / bullfrog) |
| `ollama.tf` / `ollama_bullfrog.tf` | Ollama service (gx10 / bullfrog) |
| `comfyui_bullfrog.tf` | **Staged** ComfyUI on bullfrog (stretch) |
| `outputs.tf` | Endpoints + test container names (both hosts) |
| `scripts/host-prep.sh` | gx10 (Podman 4.9.3) host prep |
| `scripts/host-prep-bullfrog.sh` | bullfrog (Podman 5.7) host prep |
| `terraform.tfvars.example` | Override template (real `.tfvars` gitignored) |

## Services

- **Ollama on gx10** (`ollama.tf`, `enable_ollama`) — reuses the existing
  on-disk model library at `/srv/models/ollama`.
- **Ollama on bullfrog** (`ollama_bullfrog.tf`, `enable_bullfrog_ollama`) —
  **live**, RTX 5080, models on `/data/ollama`.
- **ComfyUI on bullfrog** (`comfyui_bullfrog.tf`, `enable_bullfrog_comfyui`) —
  **live**, UI/API on `:8188`, data on `/data/comfyui`. Image
  `yanwk/comfyui-boot:cu130-slim` (CUDA 13.0 PyTorch — the RTX 5080 is Blackwell
  / sm_120 and needs CUDA ≥12.8). See `../bugs.md` INFRA-TF-1.

> **Applying against the fleet:** a plain `tofu apply` currently wants to
> recreate the gx10 ollama container (pre-existing provider-v3.9.0 drift on
> `pid_mode`/`devices`/`ulimit` — `../bugs.md` INFRA-TF-2). Until that's
> reconciled, scope bullfrog-only changes with
> `-target=docker_container.ollama_bullfrog` so gx10 is never clobbered.

## bullfrog (host #2) — what's live and the host-prep deltas

bullfrog is fully onboarded: `docker.bullfrog` provider alias → its rootless
Podman socket, `bard-ollama` serving qwen2.5:1.5b on the RTX 5080
(`enable_bullfrog_ollama`), models on the 1.8 TB drive at `/data/ollama`, and
`bard-comfyui` on `:8188`. ComfyUI (`comfyui_bullfrog.tf`, `enable_bullfrog_comfyui`, default
false) — see `../bugs.md` INFRA-TF-1.

bullfrog runs **Ubuntu 26.04 + Podman 5.7.0 + nvidia-container-toolkit 1.19.1**,
so the host-prep recipe differs from gx10's (Podman 4.9.3). Deltas:

| Step | gx10 (Podman 4.9.3) | bullfrog (Podman 5.7.0) |
|---|---|---|
| Install | podman + nvidia-ctk pre-existing | `apt install podman nvidia-container-toolkit podman-docker` (NVIDIA apt repo added; `podman-docker` needed for the provider's `docker system dial-stdio` SSH transport) |
| CDI spec | `host-prep.sh` generates + **downgrades to 0.6.0** (4.9.3's parser rejects 0.7.0) | **skip** — the toolkit ships an `nvidia-cdi-refresh` systemd unit that auto-generates `/var/run/cdi/nvidia.yaml` at **0.7.0**, which Podman 5.7 parses natively. Generating a second spec at `/etc/cdi` would duplicate `nvidia.com/gpu=all`. |
| Default runtime | nvidia set as default OCI runtime (compat API ignores per-container runtime) | **same** — still set nvidia as default; `local.gpu_env` (`NVIDIA_VISIBLE_DEVICES`) drives injection identically |
| Socket / linger | rootless socket + linger | `loginctl enable-linger`; `systemctl --user enable --now podman.socket` |
| `/etc/containers/nodocker` | n/a | created, so the podman-docker wrapper's banner doesn't pollute the dial-stdio stream |

Net: on bullfrog, host prep = `apt install` + linger + socket + **only the
default-runtime step** of `host-prep.sh` (the CDI generate/downgrade is a no-op
to skip). The same `local.gpu_env` works on both hosts.

### Adding a further host

1. Make `ssh <host>` work; install podman + nvidia-container-toolkit +
   podman-docker; enable linger + the rootless socket; set nvidia as the default
   runtime (downgrade the CDI spec only if Podman < 5).
2. Add per-host variables (`<host>_ssh_user`, `<host>_podman_host`, …), a
   `<host>_docker_host` local, and a `provider "docker" { alias = "<host>" … }`.
3. Give that host's resources `provider = docker.<host>` and their own
   `enable_<host>_*` flags.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `unresolvable CDI devices nvidia.com/gpu=all` | CDI spec too new for the host's Podman. Re-run `host-prep.sh` (downgrades to 0.6.0). |
| Container can't find `nvidia-smi` / no `/dev/nvidia*` | nvidia not the default runtime, or `NVIDIA_VISIBLE_DEVICES` unset. Re-run host-prep; ensure the container has `local.gpu_env`. |
| Provider can't connect | `ssh gx10` itself failing — see `../connectivity.md` (usually wrong user or Tailscale logged out). |
| Plan wants to delete a shared base image | It shouldn't — images use `keep_locally = true`. |
