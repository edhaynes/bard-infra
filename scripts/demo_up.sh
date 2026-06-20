#!/usr/bin/env bash
# One-command bring-up for the Chris Wright demo: a real 2-node UBI+Podman fleet
# over Tailscale (this Mac + gx10/NVIDIA GB10) + the live dashboard.
#
#   ./scripts/demo_up.sh
#
# Idempotent: tears down prior agents/servers and re-runs. Demo helper, not
# shipped product (Mac + gx10 specific). See docs/demo/RUNBOOK.md.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
IMAGE="${BARDPRO_AGENT_IMAGE:-bardpro-agent:demo}"
GX10_SSH="${BARDPRO_GX10_SSH:-gx10}"
# Default to the resolvable hostname (MagicDNS on Tailnet, mDNS/hosts on LAN) —
# never a baked Tailnet IP, which won't route off-tailnet. Override with BARDPRO_GX10_IP.
GX10_IP="${BARDPRO_GX10_IP:-gx10}"
MAC_IP="${BARDPRO_MAC_TS_IP:-$(tailscale ip -4 2>/dev/null | head -1)}"
GX10_BACKEND="${BARDPRO_GX10_BACKEND:-llamacpp}"   # llamacpp = real model; echo = fast
REG_PORT=8081; ROUTER_PORT=9443

echo "==> Mac TS IP: $MAC_IP   gx10: $GX10_IP ($GX10_SSH)"

# 1) shared secret + a dashboard token (same secret to every agent)
SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
TOKEN="$(BARDPRO_JWT_SECRET="$SECRET" uv run python -c '
import os,datetime as d,jwt
n=d.datetime.now(d.UTC)
print(jwt.encode({"sub":"demo-console","iss":"bardllm-pro","iat":n,"exp":n+d.timedelta(days=1)},os.environ["BARDPRO_JWT_SECRET"],algorithm="HS256"))')"

# 2) build the UBI agent image on both nodes (llama layer is cached → fast)
echo "==> building agent image on the Mac"; podman build -t "$IMAGE" -f agent/Containerfile . >/tmp/bardpro_mac_build.log 2>&1 || { echo "Mac build failed (see /tmp/bardpro_mac_build.log)"; exit 1; }
echo "==> syncing + building on gx10"; rsync -az -e ssh --exclude .venv --exclude node_modules --exclude dist --exclude clients --exclude models ./ "$GX10_SSH":~/bardpro-demo/ >/dev/null
ssh "$GX10_SSH" "cd ~/bardpro-demo && podman build -t $IMAGE -f agent/Containerfile . >/tmp/bardpro_gx10_build.log 2>&1" || { echo "gx10 build failed"; exit 1; }

# 3) capability profiles (heterogeneous fleet)
printf 'name: mac-laptop\ncpus: 18\nmemory: 48g\ngpus: Apple M5 Max\n' > ~/mac-laptop.yaml
ssh "$GX10_SSH" "printf 'name: gx10-gb10\ncpus: 20\nmemory: 121g\ngpus: all\n' > ~/gx10-gb10.yaml"

# 4) serve-mode (Registry + Router) on the Mac, plain-HTTP + CORS, 0.0.0.0
pkill -f demo_serve 2>/dev/null; sleep 1
BARDPRO_JWT_SECRET="$SECRET" PYTHONUNBUFFERED=1 nohup uv run python scripts/demo_serve.py >/tmp/bardpro_serve.log 2>&1 &
sleep 6
curl -fsS -m3 "http://$MAC_IP:$REG_PORT/healthz" >/dev/null && echo "==> registry up" || { echo "registry failed to start"; exit 1; }

# 5) agents — Mac (CPU) + gx10 (GB10, $GX10_BACKEND). Explicit http:// so the router talks plain HTTP.
# Default-deny runtime: cap-drop=all, no-new-privileges, read-only rootfs (+tmpfs /tmp),
# pids-limit. Plain HTTP over Tailscale requires the explicit ALLOW_INSECURE_HTTP opt-in.
HARDEN="--cap-drop=all --security-opt=no-new-privileges --read-only --tmpfs /tmp --pids-limit=512"
podman rm -f mac-laptop >/dev/null 2>&1
podman run -d --name mac-laptop $HARDEN \
  -e BARDPRO_JWT_SECRET="$SECRET" -e BARDPRO_SELF_REGISTER=true -e BARDPRO_REGISTRY_SCHEME=http \
  -e BARDPRO_ALLOW_INSECURE_HTTP=true \
  -e BARDPRO_REGISTRY_HOST=host.containers.internal -e BARDPRO_REGISTRY_PORT=$REG_PORT \
  -e BARDPRO_AGENT_ID=mac-laptop -e BARDPRO_AGENT_PORT=8452 \
  -e BARDPRO_ADVERTISED_ADDRESS="http://host.containers.internal:8452" -e BARDPRO_CAPABILITIES='gpu,llm' \
  -e BARDPRO_POWER_PROFILE_PATH=/profile.yaml -v ~/mac-laptop.yaml:/profile.yaml:ro \
  "$IMAGE" >/dev/null && echo "==> mac-laptop agent up"

ssh "$GX10_SSH" "podman rm -f gx10-gb10 >/dev/null 2>&1
podman run -d --name gx10-gb10 --network host $HARDEN \
  -e BARDPRO_JWT_SECRET=$SECRET -e BARDPRO_SELF_REGISTER=true -e BARDPRO_REGISTRY_SCHEME=http \
  -e BARDPRO_ALLOW_INSECURE_HTTP=true \
  -e BARDPRO_REGISTRY_HOST=$MAC_IP -e BARDPRO_REGISTRY_PORT=$REG_PORT \
  -e BARDPRO_AGENT_ID=gx10-gb10 -e BARDPRO_AGENT_PORT=8451 \
  -e BARDPRO_ADVERTISED_ADDRESS=http://$GX10_IP:8451 -e BARDPRO_CAPABILITIES='gpu,llm' \
  -e BARDPRO_INFERENCE_BACKEND=$GX10_BACKEND \
  -e BARDPRO_POWER_PROFILE_PATH=/profile.yaml -v ~/gx10-gb10.yaml:/profile.yaml:ro \
  -v bardpro-models:/opt/bardpro/models \
  $IMAGE >/dev/null && echo '==> gx10-gb10 agent up ($GX10_BACKEND)'"

# 5b) poll until both nodes have registered (gx10 registers only after its model loads)
echo "==> waiting for the fleet to register (model load on first run can take ~1-2 min)"
for i in $(seq 1 60); do
  N=$(curl -fsS -m5 "http://$MAC_IP:$REG_PORT/agents" -H "Authorization: Bearer $TOKEN" 2>/dev/null | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  [ "$N" = "2" ] && { echo "==> 2 nodes registered"; break; }
  sleep 3
done

# 6) dashboard env + dev server
cat > clients/demo-console/.env.local <<ENV
VITE_REGISTRY_BASE=http://$MAC_IP:$REG_PORT
VITE_ROUTER_BASE=http://$MAC_IP:$ROUTER_PORT
VITE_TOKEN=$TOKEN
ENV
pkill -f 'vite' 2>/dev/null; sleep 1
( cd clients/demo-console && nohup npm run dev >/tmp/bardpro_console_dev.log 2>&1 & )
sleep 3

# 7) status
echo; echo "==> FLEET"; curl -fsS -m5 "http://$MAC_IP:$REG_PORT/agents" -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json;[print("   -",a["agentId"],"·",a["powerProfile"]["cpus"],"cpu ·",a["powerProfile"]["memory"],"· GPU:",a["powerProfile"]["gpus"]) for a in json.load(sys.stdin)]'
echo "==> POOL  "; curl -fsS -m5 "http://$MAC_IP:$REG_PORT/pool" -H "Authorization: Bearer $TOKEN"; echo
echo; echo "==> Dashboard:  http://localhost:5173    (Run inference → lands on the GB10)"
echo "==> Stop with:  ./scripts/demo_down.sh"
