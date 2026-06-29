# GPU smoke test: a one-shot container that runs `nvidia-smi` to prove CDI GPU
# passthrough through the provider works end to end. Opt-in via enable_gpu_test;
# apply it to verify the foundation, capture the logs, then destroy.

resource "docker_image" "gpu_test" {
  count        = var.enable_gpu_test ? 1 : 0
  name         = var.gpu_test_image
  keep_locally = true # shared base image — never delete it on destroy
}

resource "docker_container" "gpu_test" {
  count   = var.enable_gpu_test ? 1 : 0
  name    = var.gpu_test_container_name
  image   = docker_image.gpu_test[0].image_id
  command = ["nvidia-smi"]

  # One-shot: it runs nvidia-smi and exits. Don't treat exit as an apply error,
  # and don't auto-restart.
  must_run = false
  restart  = "no"

  # The sole GPU knob (see locals.gpu_env / README host-prep).
  env = local.gpu_env
}
