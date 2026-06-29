# Docker/Podman provider pointed at the remote rootless Podman socket over SSH.
# No credentials live here: auth is the operator's SSH key (ssh-agent / key in
# ~/.ssh), never committed.

provider "docker" {
  host = local.docker_host

  # accept-new lets first-contact with a new host succeed without an interactive
  # prompt while still pinning the key thereafter.
  ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
}
