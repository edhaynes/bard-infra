#!/bin/sh
# Fetch the GGUF model used by the llama.cpp inference backend.
# Cross-platform sibling: fetch_model.ps1 for Windows.
#
# Everything is config-driven (CLAUDE.md §1); nothing is hardcoded beyond the
# documented defaults below, and every value is overridable by env var.
#
#   BARDPRO_MODEL_URL     Source URL of the GGUF (default: small Qwen2.5-0.5B Q4).
#   BARDPRO_MODEL_DIR     Target dir (default: ./models).
#   BARDPRO_MODEL_SHA256  Optional: expected SHA-256; verified if set.
#
# Idempotent: a non-empty target file is left untouched. Fails loudly on any
# download or verification error (CLAUDE.md §10) — no silent fallback.
set -eu

# Small (~350 MB) instruct GGUF, Q4_K_M quant. Apache-2.0 license. Chosen as a
# laptop/CI-friendly default that runs without a GPU; override for production.
DEFAULT_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"

MODEL_URL="${BARDPRO_MODEL_URL:-$DEFAULT_MODEL_URL}"
MODEL_DIR="${BARDPRO_MODEL_DIR:-./models}"
MODEL_PATH="${MODEL_DIR}/model.gguf"

# Idempotent: skip if already present and non-empty.
if [ -s "${MODEL_PATH}" ]; then
  echo "fetch_model: ${MODEL_PATH} already present; skipping download." >&2
  exit 0
fi

mkdir -p "${MODEL_DIR}"

echo "fetch_model: downloading ${MODEL_URL}" >&2
echo "fetch_model:   -> ${MODEL_PATH}" >&2

# Download to a temp file first so a failed/partial download never leaves a
# truncated model.gguf that the idempotency check would later accept.
TMP_PATH="${MODEL_PATH}.partial"
trap 'rm -f "${TMP_PATH}"' EXIT INT TERM

if ! curl -fL --retry 3 --retry-delay 2 -o "${TMP_PATH}" "${MODEL_URL}"; then
  echo "fetch_model: ERROR — download failed from ${MODEL_URL}" >&2
  exit 1
fi

if [ ! -s "${TMP_PATH}" ]; then
  echo "fetch_model: ERROR — downloaded file is empty: ${MODEL_URL}" >&2
  exit 1
fi

# Optional checksum verification when BARDPRO_MODEL_SHA256 is set.
if [ -n "${BARDPRO_MODEL_SHA256:-}" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL="$(sha256sum "${TMP_PATH}" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    ACTUAL="$(shasum -a 256 "${TMP_PATH}" | awk '{print $1}')"
  else
    echo "fetch_model: ERROR — BARDPRO_MODEL_SHA256 set but no sha256sum/shasum found" >&2
    exit 1
  fi
  if [ "${ACTUAL}" != "${BARDPRO_MODEL_SHA256}" ]; then
    echo "fetch_model: ERROR — checksum mismatch" >&2
    echo "fetch_model:   expected ${BARDPRO_MODEL_SHA256}" >&2
    echo "fetch_model:   actual   ${ACTUAL}" >&2
    exit 1
  fi
  echo "fetch_model: checksum OK" >&2
fi

mv "${TMP_PATH}" "${MODEL_PATH}"
trap - EXIT INT TERM
echo "fetch_model: done -> ${MODEL_PATH}" >&2
