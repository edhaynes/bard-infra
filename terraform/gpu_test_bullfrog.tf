# GPU smoke test on bullfrog — same one-shot nvidia-smi proof as gpu_test.tf,
# but against the bullfrog host (docker.bullfrog alias). Opt-in via
# enable_bullfrog_gpu_test; apply to verify the RTX 5080, capture logs, destroy.

resource "docker_image" "gpu_test_bullfrog" {
  provider     = docker.bullfrog
  count        = var.enable_bullfrog_gpu_test ? 1 : 0
  name         = var.gpu_test_image
  keep_locally = true # shared base image — never delete it on destroy
}

resource "docker_container" "gpu_test_bullfrog" {
  provider = docker.bullfrog
  count    = var.enable_bullfrog_gpu_test ? 1 : 0
  name     = var.bullfrog_gpu_test_container_name
  image    = docker_image.gpu_test_bullfrog[0].image_id
  command  = ["nvidia-smi"]

  # One-shot: runs nvidia-smi and exits. Don't treat exit as an apply error.
  must_run = false
  restart  = "no"

  # The sole GPU knob (see locals.gpu_env / README host-prep).
  env = local.gpu_env
}
