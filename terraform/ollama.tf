# Ollama — local LLM serving on the GPU, reusing the existing on-disk model
# library at var.ollama_models_host_dir (no models are pulled by this stack).
#
# STAGED, NOT DEPLOYED. enable_ollama defaults to false. This resource is ready
# to run (GPU path is proven by the gpu_test resource), but the foundation task
# was explicitly "don't build the real services yet"; enabling it deploys a
# long-running service to the shared gx10 host and needs Eddie's explicit
# go-ahead: `tofu apply -var enable_ollama=true`. Verify after:
#   ssh gx10 podman exec bard-ollama ollama list   # lists the existing models

resource "docker_image" "ollama" {
  count        = var.enable_ollama ? 1 : 0
  name         = var.ollama_image
  keep_locally = true # don't delete the (large) image on destroy
}

resource "docker_container" "ollama" {
  count   = var.enable_ollama ? 1 : 0
  name    = var.ollama_container_name
  image   = docker_image.ollama[0].image_id
  restart = "unless-stopped"

  # GPU (local.gpu_env) + serve on all interfaces so the published port works,
  # + point OLLAMA_MODELS at the bind-mounted existing model library.
  env = concat(local.gpu_env, [
    "OLLAMA_HOST=0.0.0.0",
    "OLLAMA_MODELS=${var.ollama_models_container_dir}",
  ])

  volumes {
    host_path      = var.ollama_models_host_dir
    container_path = var.ollama_models_container_dir
  }

  ports {
    internal = var.ollama_port
    external = var.ollama_port
  }
}
