#!/bin/bash
# Build the Bard agent bootc image (RHEL 10 image-mode). Mirrors
# rhel10_imagemode/build.sh.
#
# PREREQ: run on a SUBSCRIBED RHEL/fedora host (subscription-manager register),
# because `dnf update` inside the rhel-bootc base pulls from entitled repos.
# On Mac/Windows + Podman Desktop, ssh into the podman machine first:
#     podman machine ssh --username core
# (the fedora-core VM can run subscription-manager). If you do NOT have a
# subscribed build host, you don't build at all — USE EXISTING: run-existing.sh.
set -euo pipefail

IMAGE="${BARD_BOOTC_IMAGE:-quay.io/ehaynes/bard-bootc:0.1.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SECRET_FILE="${BARD_OPERATOR_PASSWORD_FILE:-${HERE}/operator-password.txt}"

if [[ ! -f "${SECRET_FILE}" ]]; then
  echo "Error: operator-password secret '${SECRET_FILE}' not found." >&2
  echo "  Create it (one line, the 'bard' user's password), gitignored:" >&2
  echo "    printf '%s' '<password>' > ${SECRET_FILE}" >&2
  exit 1
fi

echo "Building bootc image: ${IMAGE}"
podman build \
  --secret id=bard-operator-password,src="${SECRET_FILE}" \
  -t "${IMAGE}" \
  -f "${HERE}/Containerfile" \
  "${HERE}"

echo
echo "Built ${IMAGE}. Next:"
echo "  podman push ${IMAGE}            # to Quay (login first: podman login quay.io)"
echo "  ./run-existing.sh              # create the qcow2 + boot it as a VM"
echo "  # update a running node later:  ansible-playbook ansible/bootc_update.yml"
