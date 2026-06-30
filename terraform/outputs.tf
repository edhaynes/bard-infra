output "docker_host" {
  description = "The Docker-compatible (Podman) endpoint this stack manages."
  value       = local.docker_host
}

output "gpu_test_container" {
  description = "Name of the GPU smoke-test container (empty when disabled). Inspect with: ssh <host> podman logs <name>"
  value       = var.enable_gpu_test ? var.gpu_test_container_name : ""
}

output "ollama_endpoint" {
  description = "Ollama HTTP API endpoint (empty when disabled)."
  value       = var.enable_ollama ? "http://${var.podman_host}:${var.ollama_port}" : ""
}

output "bullfrog_docker_host" {
  description = "The bullfrog Podman endpoint this stack manages."
  value       = local.bullfrog_docker_host
}

output "bullfrog_ollama_endpoint" {
  description = "bullfrog Ollama HTTP API endpoint (empty when disabled)."
  value       = var.enable_bullfrog_ollama ? "http://${var.bullfrog_podman_host}:${var.bullfrog_ollama_port}" : ""
}

output "bullfrog_comfyui_endpoint" {
  description = "bullfrog ComfyUI HTTP endpoint (empty when disabled)."
  value       = var.enable_bullfrog_comfyui ? "http://${var.bullfrog_podman_host}:${var.bullfrog_comfyui_port}" : ""
}
