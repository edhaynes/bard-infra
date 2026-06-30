# Ollama on bullfrog — local LLM serving on the RTX 5080. bullfrog is the x86
# inference/serving node; its models live on the 1.8 TB drive at
# var.bullfrog_ollama_models_host_dir (created by host bootstrap, owned by the
# rootless user, so the container can pull/write models). GPU via the proven
# default-runtime + NVIDIA_VISIBLE_DEVICES path (local.gpu_env).
#
# Opt-in via enable_bullfrog_ollama. Verify after:
#   curl http://bullfrog:11434/api/tags
#   ssh bullfrog podman exec bard-ollama ollama list

resource "docker_image" "ollama_bullfrog" {
  provider     = docker.bullfrog
  count        = var.enable_bullfrog_ollama ? 1 : 0
  name         = var.bullfrog_ollama_image
  keep_locally = true # don't delete the (large) image on destroy
}

resource "docker_container" "ollama_bullfrog" {
  provider = docker.bullfrog
  count    = var.enable_bullfrog_ollama ? 1 : 0
  name     = var.bullfrog_ollama_container_name
  image    = docker_image.ollama_bullfrog[0].image_id
  restart  = "unless-stopped"

  # GPU (local.gpu_env) + serve on all interfaces so the published port works,
  # + point OLLAMA_MODELS at the bind-mounted models dir on the big drive.
  env = concat(local.gpu_env, [
    "OLLAMA_HOST=0.0.0.0",
    "OLLAMA_MODELS=${var.bullfrog_ollama_models_container_dir}",
  ])

  volumes {
    host_path      = var.bullfrog_ollama_models_host_dir
    container_path = var.bullfrog_ollama_models_container_dir
  }

  ports {
    internal = var.bullfrog_ollama_port
    external = var.bullfrog_ollama_port
  }
}
