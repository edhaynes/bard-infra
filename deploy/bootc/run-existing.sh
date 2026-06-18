#!/bin/bash
# USE EXISTING — for Mac/Windows + Podman Desktop (or anyone WITHOUT a subscribed
# build host). Pull a PRE-BUILT Bard bootc image from Quay and turn it into a
# bootable qcow2 VM disk with bootc-image-builder. No `dnf update`, no
# subscription-manager — the image is already built; you only convert + boot it.
#
# Run inside the podman machine on Mac/Windows:
#     podman machine ssh --username core   # then: cd ... && ./run-existing.sh
set -euo pipefail

IMAGE="${BARD_BOOTC_IMAGE:-quay.io/ehaynes/bard-bootc:0.1.0}"
OUT="${BARD_BOOTC_OUT:-$HOME/bard-bootc-out}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${HERE}/config.json"   # user/SSH-key/filesystem (mirror rhel10_imagemode)

mkdir -p "${OUT}"
echo "Pulling pre-built image: ${IMAGE}"
podman pull "${IMAGE}"

echo "Converting to a bootable qcow2 (bootc-image-builder) → ${OUT}/qcow2/disk.qcow2"
podman run --rm -it --privileged --pull=newer \
  --security-opt label=type:unconfined_t \
  -v "${OUT}":/output \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  ${CONFIG:+-v "${CONFIG}":/config.json:ro} \
  registry.redhat.io/rhel10/bootc-image-builder:latest \
  --type qcow2 \
  ${CONFIG:+--config /config.json} \
  "${IMAGE}"

echo
echo "Done. Boot the qcow2 as a VM:"
echo "  • Mac: open ${OUT}/qcow2/disk.qcow2 in UTM (your rhel10_imagemode path)"
echo "  • RHEL/libvirt: virt-install --import --disk ${OUT}/qcow2/disk.qcow2 ..."
echo "Then SSH in (the 'ubi terminal' tab does this): ssh bard@<vm-ip>"
echo "The agent (Quadlet) starts on boot; its API is on :8444."
