output "docker_host" {
  description = "The Docker-compatible (Podman) endpoint this stack manages."
  value       = local.docker_host
}

output "gpu_test_container" {
  description = "Name of the GPU smoke-test container (empty when disabled). Inspect with: ssh <host> podman logs <name>"
  value       = var.enable_gpu_test ? var.gpu_test_container_name : ""
}
