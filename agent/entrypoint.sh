#!/bin/sh
# Agent container entrypoint (Linux, inside the UBI-9 image).
# Optionally starts the llama.cpp inference server, then the agent API.
set -eu

# sshd is installed (the v2 CLI-tab transport, ADR-0004 / Sprint 5) but is
# deliberately NOT started in the MVP — default-deny. The container also runs
# as the non-root `bard` user, which could not start sshd anyway.

# --- Inference backend (Sprint 1) -------------------------------------------
# echo  (or unset): no model server needed; the echo engine answers locally.
# llamacpp        : launch the co-located llama.cpp OpenAI-compatible server and
#                   wait for it to become healthy before starting the API.
BACKEND="${BARDPRO_INFERENCE_BACKEND:-echo}"
MODEL_DIR="${BARDPRO_MODEL_DIR:-/opt/bardpro/models}"
MODEL_PATH="${MODEL_DIR}/model.gguf"
LLAMA_BIN="/usr/local/bin/llama-server"
LLAMA_HOST="127.0.0.1"
LLAMA_PORT="8080"
LLAMA_THREADS="${BARDPRO_LLAMA_THREADS:-}"

if [ "${BACKEND}" = "llamacpp" ]; then
  # Fetch the model on first run if it is missing (idempotent, fails loudly).
  # Script location is overridable; defaults to the in-image path the Containerfile
  # copies it to (/opt/bardpro/scripts), which is independent of $0's location.
  FETCH_SCRIPT="${BARDPRO_FETCH_SCRIPT:-/opt/bardpro/scripts/fetch_model.sh}"
  if [ ! -s "${MODEL_PATH}" ]; then
    echo "entrypoint: model missing at ${MODEL_PATH}; fetching..." >&2
    BARDPRO_MODEL_DIR="${MODEL_DIR}" sh "${FETCH_SCRIPT}"
  fi

  if [ ! -x "${LLAMA_BIN}" ]; then
    echo "entrypoint: ERROR — ${LLAMA_BIN} not found or not executable" >&2
    exit 1
  fi

  echo "entrypoint: starting llama-server on ${LLAMA_HOST}:${LLAMA_PORT}" >&2
  THREAD_FLAG=""
  if [ -n "${LLAMA_THREADS}" ]; then
    THREAD_FLAG="--threads ${LLAMA_THREADS}"
  fi
  # shellcheck disable=SC2086  # THREAD_FLAG is an intentional word-split flag.
  "${LLAMA_BIN}" \
    --model "${MODEL_PATH}" \
    --host "${LLAMA_HOST}" \
    --port "${LLAMA_PORT}" \
    ${THREAD_FLAG} &
  LLAMA_PID=$!

  # Wait for the server to become healthy (bounded retry loop). Fail loudly if
  # it never comes up — and surface an early crash of the background process.
  HEALTH_URL="http://${LLAMA_HOST}:${LLAMA_PORT}/health"
  MAX_ATTEMPTS="${BARDPRO_LLAMA_HEALTH_RETRIES:-60}"
  attempt=1
  ready=0
  while [ "${attempt}" -le "${MAX_ATTEMPTS}" ]; do
    if ! kill -0 "${LLAMA_PID}" 2>/dev/null; then
      echo "entrypoint: ERROR — llama-server exited before becoming healthy" >&2
      exit 1
    fi
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
      ready=1
      break
    fi
    echo "entrypoint: waiting for llama-server (${attempt}/${MAX_ATTEMPTS})..." >&2
    attempt=$((attempt + 1))
    sleep 2
  done

  if [ "${ready}" -ne 1 ]; then
    echo "entrypoint: ERROR — llama-server not healthy after ${MAX_ATTEMPTS} attempts" >&2
    kill "${LLAMA_PID}" 2>/dev/null || true
    exit 1
  fi
  echo "entrypoint: llama-server healthy." >&2
fi

exec uvicorn agent.main:app --host 0.0.0.0 --port "${BARDPRO_AGENT_PORT:-8444}"
