# All tunables live here (coding-rules §2: config over hardcoding; no magic
# values in resources). Defaults make the stack run against gx10 with no
# terraform.tfvars at all; override per-host via terraform.tfvars.

# ---------------------------------------------------------------------------
# Host / connection
# ---------------------------------------------------------------------------

variable "ssh_user" {
  description = "SSH user on the Podman host (fleet convention: ehaynes)."
  type        = string
  default     = "ehaynes"
}

variable "podman_host" {
  description = "SSH target for the Podman host. Prefer the stable Tailscale MagicDNS name (see connectivity.md) over an IP."
  type        = string
  default     = "gx10"
}

variable "podman_socket_path" {
  description = "Absolute path to the rootless Podman API socket on the host."
  type        = string
  default     = "/run/user/1000/podman/podman.sock"
}

# ---------------------------------------------------------------------------
# GPU passthrough (CDI via the nvidia default runtime — see README host-prep)
# ---------------------------------------------------------------------------

variable "gpu_visible_devices" {
  description = "Value for NVIDIA_VISIBLE_DEVICES. 'all' exposes every GPU; or a UUID/index. 'void'/'' disables GPU for a container."
  type        = string
  default     = "all"
}

variable "gpu_driver_capabilities" {
  description = "Value for NVIDIA_DRIVER_CAPABILITIES (e.g. 'all', or 'compute,utility')."
  type        = string
  default     = "all"
}

# ---------------------------------------------------------------------------
# GPU smoke-test container (opt-in; proves the foundation, then destroy)
# ---------------------------------------------------------------------------

variable "enable_gpu_test" {
  description = "When true, create the one-shot GPU test container that runs nvidia-smi. Apply to prove GPU passthrough, then destroy."
  type        = bool
  default     = false
}

variable "gpu_test_image" {
  description = "Image for the GPU smoke test. nvidia-smi is injected into the container by the CDI spec, so a plain Red Hat-family base suffices."
  type        = string
  default     = "quay.io/fedora/fedora:41"
}

variable "gpu_test_container_name" {
  description = "Name of the GPU smoke-test container."
  type        = string
  default     = "bard-gpu-test"
}
