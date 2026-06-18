#!/bin/sh
# One-command local MVP demo on macOS (also works on Linux).
# Spins up Registry + Agent + Router on localhost TLS and runs a real request.
set -eu

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
fi

uv venv --quiet
uv pip install -e ".[dev]" --quiet
exec uv run python scripts/smoke_local.py
