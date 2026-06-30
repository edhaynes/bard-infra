# Derived values. Building the Docker host URL from parts (rather than a single
# opaque string) keeps it parameterized per coding-rules §2/§5 and makes adding
# a second host a matter of new variable values / a provider alias.

locals {
  # ssh://<user>@<host><abs-socket-path> — the kreuzwerker/docker provider
  # tunnels the Docker-compatible API over SSH using the system ssh client
  # (gx10 must be reachable via `ssh <podman_host>` — see connectivity.md).
  docker_host = "ssh://${var.ssh_user}@${var.podman_host}${var.podman_socket_path}"

  # Second host (bullfrog) — same URL shape, its own variables. Consumed by the
  # `docker.bullfrog` provider alias so bullfrog is a first-class managed host.
  bullfrog_docker_host = "ssh://${var.bullfrog_ssh_user}@${var.bullfrog_podman_host}${var.bullfrog_podman_socket_path}"

  # Standard NVIDIA env that the nvidia-container-runtime (set as Podman's
  # default runtime during host-prep) keys off to CDI-inject the GPU. This is
  # the only per-container knob needed for GPU access through the compat API on
  # Podman 4.9.3 (HostConfig.Runtime and DeviceRequests are ignored there).
  gpu_env = [
    "NVIDIA_VISIBLE_DEVICES=${var.gpu_visible_devices}",
    "NVIDIA_DRIVER_CAPABILITIES=${var.gpu_driver_capabilities}",
  ]
}
