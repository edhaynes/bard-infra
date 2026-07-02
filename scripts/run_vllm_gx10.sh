#!/usr/bin/env bash
# Bring up the two-tier vLLM LLM router on gx10 (GB10 / aarch64) — the little
# model up first, the big model warming in the background (feature: vLLM router
# plugin; ADR-0018 owner-enabled inference resource). Run ON gx10.
#
# CRITICAL: gx10's root fs is ~99% full, so ALL container storage AND model
# weights go on /srv/models (623 GB free) — never the default ~/.local/share.
#
#   ssh gx10 'bash -s' < scripts/run_vllm_gx10.sh          # defaults
#   IMAGE=... LITTLE_MODEL=... BIG_MODEL=... ssh gx10 'bash -s' < scripts/run_vllm_gx10.sh
#
# Env (all overridable — no hardcoding, coding-rules §2):
set -euo pipefail

IMAGE="${IMAGE:-docker.io/hellohal2064/vllm-dgx-spark-gb10:latest}"  # swap for your own GB10 vLLM image
LITTLE_MODEL="${LITTLE_MODEL:-Qwen/Qwen3-0.6B}"
BIG_MODEL="${BIG_MODEL:-Qwen/Qwen3-8B}"          # empty = little only
LITTLE_PORT="${LITTLE_PORT:-8000}"
BIG_PORT="${BIG_PORT:-8001}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.85}"

# Storage kept OFF the full root: podman graph + HF weight cache both on /srv.
STORE_ROOT="${STORE_ROOT:-/srv/models/vllm-containers/storage}"
STORE_RUNROOT="${STORE_RUNROOT:-/srv/models/vllm-containers/run}"
HF_CACHE="${HF_CACHE:-/srv/models/hf}"
mkdir -p "$STORE_ROOT" "$STORE_RUNROOT" "$HF_CACHE"

PODMAN=(podman --root "$STORE_ROOT" --runroot "$STORE_RUNROOT")

echo "== pulling $IMAGE (to /srv/models storage) =="
"${PODMAN[@]}" pull "$IMAGE"

# One vLLM OpenAI-compatible server per tier. GPU via the CDI spec already on the
# host (/etc/cdi/nvidia.yaml); weights cached on the big volume.
run_tier() {
  local name="$1" model="$2" port="$3"
  echo "== starting tier '$name' → $model on :$port =="
  "${PODMAN[@]}" run -d --replace --name "bard-vllm-$name" \
    --device nvidia.com/gpu=all \
    --network host \
    -v "$HF_CACHE":/root/.cache/huggingface:Z \
    -e HF_HOME=/root/.cache/huggingface \
    "$IMAGE" \
    --model "$model" \
    --port "$port" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEM_UTIL"
}

# Little model first — this is the tier that answers in seconds.
run_tier little "$LITTLE_MODEL" "$LITTLE_PORT"

# Big model warms in the background (its own container; slow to download + load).
if [ -n "$BIG_MODEL" ]; then
  run_tier big "$BIG_MODEL" "$BIG_PORT"
  echo "== big model '$BIG_MODEL' loading in the background on :$BIG_PORT =="
fi

echo "== waiting for the little tier /health on :$LITTLE_PORT =="
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${LITTLE_PORT}/health" >/dev/null 2>&1; then
    echo "LITTLE READY: http://127.0.0.1:${LITTLE_PORT}/v1  (model=$LITTLE_MODEL)"
    exit 0
  fi
  sleep 5
done
echo "LITTLE tier did not report healthy in time — check: ${PODMAN[*]} logs bard-vllm-little" >&2
exit 1
