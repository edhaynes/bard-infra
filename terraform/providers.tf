# Docker/Podman provider pointed at the remote rootless Podman socket over SSH.
# No credentials live here: auth is the operator's SSH key (ssh-agent / key in
# ~/.ssh), never committed.

provider "docker" {
  host = local.docker_host

  # accept-new lets first-contact with a new host succeed without an interactive
  # prompt while still pinning the key thereafter.
  ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
}

# Second host: bullfrog (x86_64 / RTX 5080). Same provider, distinct alias and
# socket. Resources select it with `provider = docker.bullfrog`.
provider "docker" {
  alias = "bullfrog"
  host  = local.bullfrog_docker_host

  ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
}
