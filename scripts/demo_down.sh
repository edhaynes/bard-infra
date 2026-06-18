#!/usr/bin/env bash
# Tear down the Chris Wright demo fleet (Mac + gx10).
set -uo pipefail
GX10_SSH="${BARDPRO_GX10_SSH:-gx10}"
pkill -f demo_serve 2>/dev/null && echo "stopped serve-mode" || true
pkill -f 'vite' 2>/dev/null && echo "stopped dashboard" || true
podman rm -f mac-laptop 2>/dev/null && echo "removed mac-laptop" || true
ssh "$GX10_SSH" 'podman rm -f gx10-gb10 2>/dev/null' && echo "removed gx10-gb10" || true
echo "demo down."
