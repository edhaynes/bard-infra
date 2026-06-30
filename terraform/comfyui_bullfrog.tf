# ComfyUI on bullfrog — STRETCH. bullfrog (x86 + RTX 5080) is ComfyUI's natural
# home. Standard CUDA ComfyUI image, GPU via local.gpu_env, data persisted on
# the 1.8 TB drive. Opt-in via enable_bullfrog_comfyui (default false).

resource "docker_image" "comfyui_bullfrog" {
  provider     = docker.bullfrog
  count        = var.enable_bullfrog_comfyui ? 1 : 0
  name         = var.bullfrog_comfyui_image
  keep_locally = true # large image — never delete on destroy
}

resource "docker_container" "comfyui_bullfrog" {
  provider = docker.bullfrog
  count    = var.enable_bullfrog_comfyui ? 1 : 0
  name     = var.bullfrog_comfyui_container_name
  image    = docker_image.comfyui_bullfrog[0].image_id
  restart  = "unless-stopped"

  env = local.gpu_env

  volumes {
    host_path      = var.bullfrog_comfyui_data_host_dir
    container_path = var.bullfrog_comfyui_data_container_dir
  }

  ports {
    internal = var.bullfrog_comfyui_port
    external = var.bullfrog_comfyui_port
  }
}
