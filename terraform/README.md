# bard-infra · terraform/

OpenTofu foundation for managing **rootless Podman containers on the GPU fleet**.
This is the substrate real Bard services snap onto. It currently targets **gx10**
(the DGX Spark / NVIDIA GB10) and is parameterized so a second host (e.g.
bullfrog) can be added with variables / a provider alias.

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
| `gpu_test.tf` | Opt-in GPU smoke-test image + container |
| `ollama.tf` | **Staged, disabled-by-default** Ollama service (see below) |
| `outputs.tf` | Endpoint + test container name |
| `scripts/host-prep.sh` | One-time host GPU/runtime prep |
| `terraform.tfvars.example` | Override template (real `.tfvars` gitignored) |

## Staged services (not deployed)

- **Ollama** (`ollama.tf`) — ready to run on gx10, GPU via the proven path,
  reusing the existing on-disk model library at `/srv/models/ollama` (no models
  pulled). **Disabled by default** (`enable_ollama = false`): the foundation task
  was "don't build the real services yet," so enabling it (a long-running service
  on the shared host) needs explicit go-ahead:
  ```bash
  tofu apply -var enable_ollama=true
  ssh gx10 podman exec bard-ollama ollama list   # should list the local models
  ```
- **ComfyUI** — deferred (no reliable arm64 image; natural home is the x86
  bullfrog box, which has no Podman yet). Tracked in `../bugs.md` (INFRA-TF-1);
  add it via a provider alias once bullfrog is prepped.

## Adding a second host (e.g. bullfrog)

1. Make `ssh <host>` work and run `scripts/host-prep.sh` on it.
2. Add a second provider with an alias:
   ```hcl
   provider "docker" {
     alias = "bullfrog"
     host  = "ssh://ehaynes@bullfrog/run/user/1000/podman/podman.sock"
   }
   ```
   (or parameterize via a `for_each` over a `hosts` map and a small module).
3. Give each host's resources `provider = docker.bullfrog`.

The host coordinates already flow from `variables.tf`/`locals.tf`, so no `gx10`
literal is baked into resources.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `unresolvable CDI devices nvidia.com/gpu=all` | CDI spec too new for the host's Podman. Re-run `host-prep.sh` (downgrades to 0.6.0). |
| Container can't find `nvidia-smi` / no `/dev/nvidia*` | nvidia not the default runtime, or `NVIDIA_VISIBLE_DEVICES` unset. Re-run host-prep; ensure the container has `local.gpu_env`. |
| Provider can't connect | `ssh gx10` itself failing — see `../connectivity.md` (usually wrong user or Tailscale logged out). |
| Plan wants to delete a shared base image | It shouldn't — images use `keep_locally = true`. |
