#!/usr/bin/env bash
# host-prep.sh — one-time GPU/Podman preparation for a rootless-Podman host that
# this OpenTofu stack will manage. Run this ON the target host (e.g. gx10), as
# the rootless user (the one whose /run/user/<uid>/podman/podman.sock the
# provider connects to). Requires passwordless sudo for the CDI step.
#
#   ssh gx10 'bash -s' < terraform/scripts/host-prep.sh
#
# It is idempotent: safe to re-run. It does NOT need Terraform.
#
# What it does, and WHY (discovered against Podman 4.9.3 + nvidia-ctk 1.19.1 on
# the GB10 / gx10):
#   1. Generate the NVIDIA CDI spec (the GPU device definition Podman injects).
#   2. Downgrade the spec to CDI v0.6.0 and strip the v0.7.0-only
#      `additionalGids` field — Podman 4.9.3's bundled CDI parser rejects 0.7.0
#      ("unknown field additionalGids" / "unresolvable CDI devices"). Newer
#      Podman (>= 5.x) parses 0.7.0 natively, so this is a no-op risk: the spec
#      stays valid either way. (Remove this step once the host runs Podman 5+.)
#   3. Register nvidia-container-runtime as Podman's DEFAULT OCI runtime. This
#      is the crux: Podman 4.9.3's *Docker-compatible* API (which the
#      kreuzwerker/docker provider speaks) IGNORES per-container HostConfig.Runtime
#      and no-ops DeviceRequests{driver=cdi}. Making nvidia the default runtime
#      means GPU injection is driven purely by the NVIDIA_VISIBLE_DEVICES env var
#      (which the provider CAN set). The runtime runs in "auto" mode: it is a
#      transparent passthrough to crun/runc for containers that do NOT set
#      NVIDIA_VISIBLE_DEVICES, so non-GPU workloads are unaffected.
#   4. Restart the user Podman service so it re-reads the config.
#
# Verify afterwards with the GPU smoke test:
#   tofu apply -var enable_gpu_test=true && ssh <host> podman logs bard-gpu-test

set -euo pipefail

CDI_SPEC="/etc/cdi/nvidia.yaml"
CONTAINERS_CONF="${HOME}/.config/containers/containers.conf"
NVIDIA_RUNTIME_PATH="/usr/bin/nvidia-container-runtime"

echo "==> 1/4 Generating CDI spec at ${CDI_SPEC}"
sudo nvidia-ctk cdi generate --output="${CDI_SPEC}"

echo "==> 2/4 Downgrading CDI spec to v0.6.0 for older Podman CDI parsers"
python3 - "$CDI_SPEC" <<'PY'
import sys, yaml
path = sys.argv[1]
with open(path) as f:
    spec = yaml.safe_load(f)

def strip(node):
    if isinstance(node, dict):
        node.pop("additionalGids", None)  # CDI 0.7.0-only; rejected by Podman 4.9.3
        for v in node.values():
            strip(v)
    elif isinstance(node, list):
        for v in node:
            strip(v)

strip(spec)
spec["cdiVersion"] = "0.6.0"
with open("/tmp/nvidia-cdi.downgraded.yaml", "w") as f:
    yaml.safe_dump(spec, f, sort_keys=False)
print("    cdiVersion=0.6.0, additionalGids stripped")
PY
sudo cp /tmp/nvidia-cdi.downgraded.yaml "${CDI_SPEC}"
rm -f /tmp/nvidia-cdi.downgraded.yaml
nvidia-ctk cdi list

echo "==> 3/4 Registering nvidia-container-runtime as Podman's default runtime"
mkdir -p "$(dirname "${CONTAINERS_CONF}")"
NVIDIA_RUNTIME_PATH="${NVIDIA_RUNTIME_PATH}" CONTAINERS_CONF="${CONTAINERS_CONF}" python3 - <<'PY'
import os
conf = os.environ["CONTAINERS_CONF"]
rt = os.environ["NVIDIA_RUNTIME_PATH"]
desired = (
    "[engine]\n"
    'runtime = "nvidia"\n\n'
    "[engine.runtimes]\n"
    f'nvidia = ["{rt}"]\n'
)
cur = open(conf).read() if os.path.exists(conf) else ""
if 'runtime = "nvidia"' in cur and "nvidia-container-runtime" in cur:
    print("    already configured")
else:
    # This stack owns engine runtime config on this host; write it cleanly.
    open(conf, "w").write(desired)
    print(f"    wrote {conf}")
PY

echo "==> 4/4 Restarting user Podman service"
systemctl --user restart podman.socket || true
systemctl --user stop podman.service 2>/dev/null || true

echo "==> Done. Default runtime:"
podman info --format '{{.Host.OCIRuntime.Name}}'
