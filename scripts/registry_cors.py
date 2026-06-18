"""Registry entrypoint WITH CORS, for serving a browser console over a tailnet.

Identical to ``registry.main`` but passes ``cors_origins`` to ``create_app`` so a
browser console (Vite dev server on ``http://localhost:5173`` and the
``127.0.0.1`` variant by default) can read ``/fleet`` cross-origin.

Run with::

    uv run uvicorn registry_cors:app \
        --app-dir scripts --host 0.0.0.0 --port 8081

Allowed origins come from ``BARDPRO_CONSOLE_ORIGINS`` (comma-separated); the
default covers the Vite dev server. This is the minimal Registry surface the
Tailscale-fabric launcher needs — device-identity / channel / plugin stores
(``registry.main``) are intentionally omitted for the lightweight fleet demo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo importable regardless of cwd / --app-dir: this file lives in
# ``<repo>/scripts/``, so the repo root is its parent's parent. Portable — no
# hardcoded home path (the throwaway /tmp original hardcoded an absolute path).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.auth import JwtVerifier  # noqa: E402
from common.config import load_config  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from registry.app import create_app  # noqa: E402
from registry.store import RegistryStore  # noqa: E402

_config = load_config()
configure_logging(_config)

_origins = os.environ.get(
    "BARDPRO_CONSOLE_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

app = create_app(
    RegistryStore(_config.registry_state_path, ttl_s=_config.agent_ttl_s),
    JwtVerifier.from_config(_config),
    cors_origins=[o.strip() for o in _origins if o.strip()],
)
