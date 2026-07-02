"""Local dev bring-up for the Fleet console (feature #91 / S5).

Serves the Registry over plain HTTP with **CORS for the console origin** and the
**ansible fact cache** wired in, then prints a ready-to-paste console token and
the exact `npm run dev` command. Read-only fleet-JWT auth (device identity off)
is enough to view `GET /nodes`.

Why this exists: `uvicorn registry.main:app` sets NO CORS (so the browser blocks
the cross-origin fetch) and mints no token. This wires both, plus the fact-cache
dir, in one command. Operational tooling — excluded from coverage like the other
server entrypoints (demo_serve.py, local_fleet_http.py).

    # from this repo/worktree root:
    BARDPRO_JWT_SECRET=dev-secret uv run python scripts/serve_console_dev.py

Env (all optional):
    BARDPRO_JWT_SECRET        signing secret (random if unset — token is printed)
    BARDPRO_REGISTRY_PORT     registry port (default 8081)
    BARDPRO_FACTS_CACHE_DIR   ansible jsonfile cache (default ansible/.facts_cache)
    CONSOLE_ORIGIN            console dev origin for CORS (default http://localhost:5173)
"""

from __future__ import annotations

import datetime as _dt
import os
import secrets
import sys
from pathlib import Path

import jwt
import uvicorn

# Make the package root importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.auth import JwtVerifier  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.store import RegistryStore  # noqa: E402

# 6060, not 6000: browsers hard-block 6000 (X11) as ERR_UNSAFE_PORT, and this is
# a browser-facing API. Unique to the Fleet console (Eddie 2026-07-02). Override
# with BARDPRO_REGISTRY_PORT if 6060 is taken — keep it off the browser unsafe list.
PORT = int(os.environ.get("BARDPRO_REGISTRY_PORT", "6060"))
ISSUER = os.environ.get("BARDPRO_JWT_ISSUER", "bardllm-pro")
ORIGIN = os.environ.get("CONSOLE_ORIGIN", "http://localhost:5173")
CACHE = os.environ.get("BARDPRO_FACTS_CACHE_DIR", "ansible/.facts_cache")
STATE = os.environ.get("BARDPRO_REGISTRY_STATE_PATH", "./registry-state.json")
SECRET = os.environ.get("BARDPRO_JWT_SECRET") or secrets.token_urlsafe(32)


def mint(sub: str) -> str:
    """A fleet-JWT the Registry's JwtVerifier accepts (sub/iss/exp, HS256)."""
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": sub, "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(days=1)},
        SECRET,
        algorithm="HS256",
    )


def build_app():
    """The Registry app with CORS + fact cache wired for the console (no TLS)."""
    return create_registry(
        RegistryStore(STATE),
        JwtVerifier(SECRET, "HS256", ISSUER),
        cors_origins=[ORIGIN],
        facts_cache_dir=CACHE,
    )


def _cache_summary() -> str:
    cache = Path(CACHE)
    if not cache.is_dir():
        return "0 nodes (dir missing — run ansible/playbooks/facts.yml first)"
    names = sorted(p.name for p in cache.iterdir() if p.is_file())
    return f"{len(names)} node(s): {', '.join(names) or 'none — run the facts.yml playbook first'}"


def main() -> None:
    app = build_app()
    token = mint("console")
    bar = "=" * 72
    print(f"\n{bar}\nFleet console dev server (feature #91 / S5)\n{bar}")
    print(f"Registry:       http://127.0.0.1:{PORT}   (GET /nodes)")
    print(f"Fact cache:     {CACHE}  →  {_cache_summary()}")
    print(f"CORS origin:    {ORIGIN}")
    print("\nStart the console in a second terminal (from this worktree):\n")
    print("  cd clients/console && \\")
    print(f"    VITE_API_BASE_URL=http://127.0.0.1:{PORT} \\")
    print(f"    VITE_API_TOKEN={token} \\")
    print("    npm run dev")
    print("\nOpen the localhost URL vite prints → Fleet tab. Ctrl-C here to stop.")
    print(f"{bar}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
