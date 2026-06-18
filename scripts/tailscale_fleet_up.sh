#!/usr/bin/env bash
# Reproducible Bard fabric bring-up over a Tailscale tailnet, addressed by
# MagicDNS names (plain HTTP over the tailnet). Productionized from the
# throwaway /tmp/bardpro-fabric live demo.
#
# Usage:
#   scripts/tailscale_fleet_up.sh <registry-node-name> [<agent-node-name> ...]
#
#   <registry-node-name>  MagicDNS name of THIS node — runs Registry (with CORS),
#                         Router, and a local Agent. The script must run on it.
#   <agent-node-name>...  MagicDNS name of each ADDITIONAL node. The script SSHes
#                         in and starts an Agent that self-registers to the
#                         registry node BY NAME and advertises http://<node>:PORT.
#
# Example (reproduces today's demo — Mac registry + gx10 agent):
#   scripts/tailscale_fleet_up.sh edwards-macbook-pro gx10
#
# Notes:
#   * MagicDNS names must resolve on every node (Tailscale up, MagicDNS enabled).
#     BARDPRO_ENFORCE_PEER_NAME_RESOLUTION stays default-true; advertised hosts
#     are resolvable names so validation passes (INFRA-1).
#   * Plain HTTP over the tailnet: BARDPRO_REGISTRY_SCHEME=http +
#     BARDPRO_ALLOW_INSECURE_HTTP=true (the tailnet is the encrypted transport).
#   * A throwaway BARDPRO_JWT_SECRET is generated at runtime, written 600 to the
#     run dir, and NEVER printed or passed on argv.
#   * Tear down with scripts/tailscale_fleet_down.sh.
set -uo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <registry-node-name> [<agent-node-name> ...]" >&2
  exit 2
fi

REG_NAME="$1"; shift
AGENT_NODES=("$@")

ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
RUN="${BARDPRO_FABRIC_RUN_DIR:-${TMPDIR:-/tmp}/bardpro-fabric}"
REG_PORT="${BARDPRO_REG_PORT:-8081}"
ROUTER_PORT="${BARDPRO_ROUTER_PORT:-9444}"
LOCAL_AGENT_PORT="${BARDPRO_LOCAL_AGENT_PORT:-8452}"
REMOTE_AGENT_PORT="${BARDPRO_REMOTE_AGENT_PORT:-8451}"
# Remote nodes already host an rsync'd checkout + built .venv here (see header).
REMOTE_DIR="${BARDPRO_REMOTE_DIR:-/srv/models/tmp/bardpro-demo}"
REMOTE_UV="${BARDPRO_REMOTE_UV:-\$HOME/.local/bin/uv}"

mkdir -p "$RUN"

# --- throwaway shared secret (>=32 bytes for HS256), 600, never echoed --------
if [ ! -f "$RUN/secret" ]; then
  python3 -c 'import secrets;print(secrets.token_urlsafe(48),end="")' > "$RUN/secret"
  chmod 600 "$RUN/secret"
fi
SECRET="$(cat "$RUN/secret")"

# --- power profile for the local node (capability info shown in /fleet) -------
printf 'name: %s\ncpus: 14\nmemory: 48g\ngpus: local\n' "$REG_NAME" > "$RUN/$REG_NAME.yaml"

export BARDPRO_JWT_SECRET="$SECRET"
export BARDPRO_ALLOW_INSECURE_HTTP=true
export BARDPRO_REGISTRY_SCHEME=http
export BARDPRO_REGISTRY_HOST="$REG_NAME"
export BARDPRO_REGISTRY_PORT="$REG_PORT"
export BARDPRO_ENFORCE_PEER_NAME_RESOLUTION=true
export BARDPRO_INFERENCE_BACKEND="${BARDPRO_INFERENCE_BACKEND:-echo}"
export BARDPRO_CONSOLE_ORIGINS="${BARDPRO_CONSOLE_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
export PYTHONUNBUFFERED=1

echo "==> registry node: $REG_NAME   agent nodes: ${AGENT_NODES[*]:-(none)}"
echo "==> run dir: $RUN"

# --- 1) Registry (CORS entrypoint, bind 0.0.0.0 so peers reach it by name) ----
nohup uv run uvicorn registry_cors:app --app-dir scripts \
  --host 0.0.0.0 --port "$REG_PORT" > "$RUN/registry.log" 2>&1 &
echo $! > "$RUN/registry.pid"

# --- 2) Router (talks to Registry by name over http) --------------------------
nohup uv run uvicorn router.main:app \
  --host 0.0.0.0 --port "$ROUTER_PORT" > "$RUN/router.log" 2>&1 &
echo $! > "$RUN/router.pid"

sleep 5
if ! curl -fsS -m5 "http://$REG_NAME:$REG_PORT/healthz" >/dev/null 2>&1; then
  echo "ERROR: registry did not come up — see $RUN/registry.log" >&2
  tail -8 "$RUN/registry.log" >&2 || true
  exit 1
fi
echo "==> registry up at http://$REG_NAME:$REG_PORT"

# --- 3) Local Agent — self-registers BY NAME, advertises itself BY NAME --------
env BARDPRO_JWT_SECRET="$SECRET" \
    BARDPRO_ALLOW_INSECURE_HTTP=true \
    BARDPRO_REGISTRY_SCHEME=http \
    BARDPRO_REGISTRY_HOST="$REG_NAME" \
    BARDPRO_REGISTRY_PORT="$REG_PORT" \
    BARDPRO_ENFORCE_PEER_NAME_RESOLUTION=true \
    BARDPRO_INFERENCE_BACKEND="$BARDPRO_INFERENCE_BACKEND" \
    BARDPRO_SELF_REGISTER=true \
    BARDPRO_AGENT_ID="$REG_NAME" \
    BARDPRO_AGENT_PORT="$LOCAL_AGENT_PORT" \
    BARDPRO_ADVERTISED_ADDRESS="http://$REG_NAME:$LOCAL_AGENT_PORT" \
    BARDPRO_CAPABILITIES="llm,cpu" \
    BARDPRO_POWER_PROFILE_PATH="$RUN/$REG_NAME.yaml" \
    PYTHONUNBUFFERED=1 \
    nohup uv run uvicorn agent.main:app \
      --host 0.0.0.0 --port "$LOCAL_AGENT_PORT" > "$RUN/$REG_NAME-agent.log" 2>&1 &
echo $! > "$RUN/$REG_NAME-agent.pid"

# --- 4) Remote Agents — one per additional node, over SSH ---------------------
# Each remote node already has an rsync'd checkout + built .venv at $REMOTE_DIR.
# The secret is staged into a 600 file on the remote and read into the env there
# (never on argv). The remote agent self-registers to $REG_NAME BY NAME and
# advertises http://<node>:$REMOTE_AGENT_PORT.
for NODE in "${AGENT_NODES[@]}"; do
  echo "==> starting agent on $NODE (ssh, $REMOTE_DIR)"
  # Stage the shared secret 600 on the remote, out of band of argv/logs.
  printf '%s' "$SECRET" | ssh "$NODE" "umask 077 && cat > $REMOTE_DIR/.secret"
  ssh "$NODE" bash -s -- "$REG_NAME" "$NODE" "$REG_PORT" "$REMOTE_AGENT_PORT" \
      "$REMOTE_DIR" "$BARDPRO_INFERENCE_BACKEND" <<'REMOTE'
set -uo pipefail
REG_NAME="$1"; NODE="$2"; REG_PORT="$3"; PORT="$4"; DIR="$5"; BACKEND="$6"
cd "$DIR"
UV="$HOME/.local/bin/uv"; command -v uv >/dev/null 2>&1 && UV="$(command -v uv)"
printf 'name: %s\ncpus: 20\nmemory: 121g\ngpus: remote\n' "$NODE" > "$DIR/$NODE.yaml"
SECRET="$(cat "$DIR/.secret")"
env BARDPRO_JWT_SECRET="$SECRET" \
    BARDPRO_ALLOW_INSECURE_HTTP=true \
    BARDPRO_REGISTRY_SCHEME=http \
    BARDPRO_REGISTRY_HOST="$REG_NAME" \
    BARDPRO_REGISTRY_PORT="$REG_PORT" \
    BARDPRO_ENFORCE_PEER_NAME_RESOLUTION=true \
    BARDPRO_INFERENCE_BACKEND="$BACKEND" \
    BARDPRO_SELF_REGISTER=true \
    BARDPRO_AGENT_ID="$NODE" \
    BARDPRO_AGENT_PORT="$PORT" \
    BARDPRO_ADVERTISED_ADDRESS="http://$NODE:$PORT" \
    BARDPRO_CAPABILITIES="llm,gpu" \
    BARDPRO_POWER_PROFILE_PATH="$DIR/$NODE.yaml" \
    PYTHONUNBUFFERED=1 \
    nohup "$UV" run uvicorn agent.main:app \
      --host 0.0.0.0 --port "$PORT" > "$DIR/$NODE-agent.log" 2>&1 &
echo $! > "$DIR/$NODE-agent.pid"
sleep 4
echo "remote_agent_pid=$(cat "$DIR/$NODE-agent.pid")"
REMOTE
  # Record the remote PID file location so teardown can reach it.
  echo "$NODE:$REMOTE_DIR/$NODE-agent.pid" >> "$RUN/remote-agents"
done

sleep 4

# --- 5) Manager JWT (sub=fabric-manager) for /fleet etc., 600, returned --------
uv run python -c "
import os, datetime as d, jwt
n = d.datetime.now(d.UTC)
print(jwt.encode(
    {'sub': 'fabric-manager', 'iss': 'bardllm-pro', 'iat': n,
     'exp': n + d.timedelta(days=1)},
    os.environ['BARDPRO_JWT_SECRET'], algorithm='HS256'), end='')
" > "$RUN/manager.jwt"
chmod 600 "$RUN/manager.jwt"
JWT="$(cat "$RUN/manager.jwt")"

# --- 6) connection info to the run dir ----------------------------------------
cat > "$RUN/connection.env" <<ENV
BARDPRO_REGISTRY_URL=http://$REG_NAME:$REG_PORT
BARDPRO_ROUTER_URL=http://$REG_NAME:$ROUTER_PORT
# Manager JWT is in $RUN/manager.jwt (600). Do not commit either file.
ENV
chmod 600 "$RUN/connection.env"

echo
echo "==> FLEET"
curl -fsS -m5 "http://$REG_NAME:$REG_PORT/agents" -H "Authorization: Bearer $JWT" \
  | python3 -c 'import sys,json;[print("   -",a.get("agentId")) for a in json.load(sys.stdin)]' \
  2>/dev/null || echo "   (agents endpoint not ready yet — check the logs)"

# --- 7) PRINT the console launch command --------------------------------------
echo
echo "==> Console (browser dashboard). Run this in another shell on $REG_NAME:"
echo
echo "    cd clients/console && \\"
echo "      VITE_API_BASE_URL=http://$REG_NAME:$REG_PORT \\"
echo "      VITE_API_TOKEN=$JWT \\"
echo "      npm run dev -- --port 5173"
echo
echo "==> Stop with: scripts/tailscale_fleet_down.sh"
