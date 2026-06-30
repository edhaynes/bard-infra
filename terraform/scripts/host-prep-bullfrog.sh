#!/usr/bin/env bash
# host-prep-bullfrog.sh — one-time GPU/Podman prep for bullfrog (x86_64, RTX 5080,
# Ubuntu 26.04 + Podman 5.7). The gx10 sibling (host-prep.sh) targets Podman
# 4.9.3 and must GENERATE + DOWNGRADE the CDI spec to 0.6.0; on bullfrog that
# step is SKIPPED — see the delta table in ../README.md. Run ON bullfrog as the
# rootless user; needs passwordless sudo. Idempotent.
#
#   ssh bullfrog 'bash -s' < terraform/scripts/host-prep-bullfrog.sh
#
# What it does, and the deltas vs gx10's host-prep.sh:
#   1. apt-install podman + nvidia-container-toolkit + podman-docker.
#      - nvidia-container-toolkit comes from NVIDIA's apt repo (not in Ubuntu).
#      - podman-docker provides /usr/bin/docker, which the kreuzwerker/docker
#        provider invokes over SSH (`docker system dial-stdio`). Without it the
#        provider can't connect.
#   2. Enable linger + the rootless podman.socket.
#   3. Create the data dir on the big drive (/data).
#   4. NO CDI generate/downgrade: nvidia-container-toolkit ships an
#      `nvidia-cdi-refresh` systemd unit that auto-writes /var/run/cdi/nvidia.yaml
#      at cdiVersion 0.7.0, which Podman 5.7 parses natively. (Generating a
#      second spec at /etc/cdi would duplicate nvidia.com/gpu=all.)
#   5. Register nvidia-container-runtime as Podman's DEFAULT runtime (same crux
#      as gx10: the Docker-compat API the provider speaks keys GPU injection off
#      NVIDIA_VISIBLE_DEVICES via the default runtime).
#   6. Touch /etc/containers/nodocker so the docker-wrapper banner doesn't
#      pollute the dial-stdio stream.
#
# Verify afterwards:
#   podman run --rm -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
#     quay.io/fedora/fedora:41 nvidia-smi      # expect: NVIDIA GeForce RTX 5080
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
RUID="$(id -u)"
export XDG_RUNTIME_DIR="/run/user/${RUID}"
DATA_DIR="${BULLFROG_DATA_DIR:-/data}"

echo "==> 1/6 apt: podman, nvidia-container-toolkit, podman-docker"
if ! command -v podman >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq podman
fi
command -v curl >/dev/null 2>&1 || sudo apt-get install -y -qq curl
command -v gpg  >/dev/null 2>&1 || sudo apt-get install -y -qq gnupg
if ! command -v nvidia-ctk >/dev/null 2>&1; then
  KEYRING=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  LISTFILE=/etc/apt/sources.list.d/nvidia-container-toolkit.list
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor --yes -o "$KEYRING"
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed "s#deb https://#deb [signed-by=${KEYRING}] https://#g" \
    | sudo tee "$LISTFILE" >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq nvidia-container-toolkit
fi
command -v docker >/dev/null 2>&1 || sudo apt-get install -y -qq podman-docker
podman --version; nvidia-ctk --version

echo "==> 2/6 Enable linger"
sudo loginctl enable-linger "$(whoami)"

echo "==> 3/6 Enable rootless podman.socket"
systemctl --user enable --now podman.socket
systemctl --user is-active podman.socket
ls -l "${XDG_RUNTIME_DIR}/podman/podman.sock"

echo "==> 4/6 Create data dir on the big drive (${DATA_DIR})"
sudo mkdir -p "${DATA_DIR}/ollama" "${DATA_DIR}/comfyui"
sudo chown -R "$(whoami):$(id -gn)" "${DATA_DIR}"

echo "==> 5/6 Register nvidia-container-runtime as Podman's default runtime"
CONF="${HOME}/.config/containers/containers.conf"
mkdir -p "$(dirname "$CONF")"
RT="$(command -v nvidia-container-runtime)"
CONF="$CONF" RT="$RT" python3 - <<'PY'
import os
conf, rt = os.environ["CONF"], os.environ["RT"]
desired = ('[engine]\nruntime = "nvidia"\n\n[engine.runtimes]\n'
           f'nvidia = ["{rt}"]\n')
cur = open(conf).read() if os.path.exists(conf) else ""
if 'runtime = "nvidia"' in cur and "nvidia-container-runtime" in cur:
    print("    already configured")
else:
    open(conf, "w").write(desired); print(f"    wrote {conf}")
PY
systemctl --user restart podman.socket
systemctl --user stop podman.service 2>/dev/null || true

echo "==> 6/6 Quiet the podman-docker wrapper banner"
sudo touch /etc/containers/nodocker

echo "==> Done. Default runtime: $(podman info --format '{{.Host.OCIRuntime.Name}}')"
