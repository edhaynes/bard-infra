# Terraform/OpenTofu + provider version constraints.
# Pinned per coding-rules §13 (versions pinned; exact resolution recorded in
# .terraform.lock.hcl, which is committed). Use OpenTofu (`tofu`), not the
# BSL-licensed HashiCorp Terraform.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    # kreuzwerker/docker speaks the Docker-compatible API exposed by both
    # Docker and Podman. We point it at gx10's rootless Podman socket over SSH.
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}
