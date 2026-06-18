#!/usr/bin/env bash
# Tear down a Tailscale fabric brought up by scripts/tailscale_fleet_up.sh.
# Kills every process by its recorded PID file in the run dir, then the remote
# agents recorded in $RUN/remote-agents. Does NOT touch anything it did not start.
#
# Usage:
#   scripts/tailscale_fleet_down.sh
set -uo pipefail

RUN="${BARDPRO_FABRIC_RUN_DIR:-${TMPDIR:-/tmp}/bardpro-fabric}"
REMOTE_DIR="${BARDPRO_REMOTE_DIR:-/srv/models/tmp/bardpro-demo}"

if [ ! -d "$RUN" ]; then
  echo "no run dir at $RUN — nothing to tear down"
  exit 0
fi

# Local processes: registry, router, and any *-agent.pid files.
for pidf in "$RUN"/registry.pid "$RUN"/router.pid "$RUN"/*-agent.pid; do
  [ -f "$pidf" ] || continue
  PID="$(cat "$pidf" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null && echo "stopped $(basename "$pidf" .pid) (pid $PID)"
  fi
  rm -f "$pidf"
done

# Remote agents: each line is "<node>:<remote-pid-file>".
if [ -f "$RUN/remote-agents" ]; then
  while IFS=: read -r NODE REMOTE_PIDF; do
    [ -n "${NODE:-}" ] || continue
    echo "stopping agent on $NODE"
    ssh "$NODE" "PID=\$(cat '$REMOTE_PIDF' 2>/dev/null || true); \
      [ -n \"\$PID\" ] && kill \"\$PID\" 2>/dev/null && echo \"  stopped pid \$PID\"; \
      rm -f '$REMOTE_PIDF'" || echo "  (ssh to $NODE failed)"
  done < "$RUN/remote-agents"
  rm -f "$RUN/remote-agents"
fi

echo "fabric down."
