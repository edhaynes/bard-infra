#!/bin/sh
# Launch the Bard agent container with high-water-mark resource limits
# (macOS via Podman Desktop, or native Linux Podman). Cross-platform sibling:
# run_agent.ps1 for Windows.
#
# Usage:
#   BARDPRO_JWT_SECRET=... ./scripts/run_agent.sh [IMAGE]
#
# Limits come from env (defaults are laptop-friendly); map to podman flags.
set -eu

IMAGE="${1:-bardllm-pro-agent:latest}"
CPUS="${BARDPRO_CPUS:-2}"
MEMORY="${BARDPRO_MEMORY:-2g}"
PIDS_LIMIT="${BARDPRO_PIDS_LIMIT:-256}"
AGENT_PORT="${BARDPRO_AGENT_PORT:-8444}"
SSH_PORT="${BARDPRO_SSH_PORT:-2222}"

GPU_FLAG=""
if [ "${BARDPRO_GPUS:-}" = "all" ]; then
  GPU_FLAG="--gpus all"
fi

# Mount the CLI-tab public key (read-only) if provided.
KEY_MOUNT=""
if [ -n "${BARDPRO_AUTHORIZED_KEYS:-}" ]; then
  KEY_MOUNT="-v ${BARDPRO_AUTHORIZED_KEYS}:/home/bard/.ssh/authorized_keys:ro,Z"
fi

set -x
exec podman run --rm \
  --cpus "${CPUS}" \
  --memory "${MEMORY}" \
  --pids-limit "${PIDS_LIMIT}" \
  ${GPU_FLAG} \
  -e BARDPRO_JWT_SECRET \
  -e BARDPRO_AGENT_ID \
  -e BARDPRO_AGENT_PORT="${AGENT_PORT}" \
  -p "${AGENT_PORT}:${AGENT_PORT}" \
  -p "${SSH_PORT}:22" \
  ${KEY_MOUNT} \
  "${IMAGE}"
