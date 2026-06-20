"""Serve-mode for the live demo (Chris Wright).

Runs the Registry + Router on this Mac over **plain HTTP + CORS**, bound to
0.0.0.0 so real UBI+Podman agents on the Mac and gx10 can self-register over
**Tailscale** (WireGuard already encrypts the hop). Prints the shared JWT secret,
a dashboard token, and the exact `podman run` commands for each node, then stays
up. Operational tooling — not product logic, excluded from coverage.

    uv run python scripts/demo_serve.py
"""

from __future__ import annotations

import datetime as _dt
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import jwt
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.auth import JwtVerifier  # noqa: E402
from common.config import Config  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.store import RegistryStore  # noqa: E402
from router.app import create_app as create_router  # noqa: E402
from router.clients import HttpAgentClient, HttpRegistryClient  # noqa: E402

REGISTRY_PORT = 8081
ROUTER_PORT = 9443  # 8443 is taken by Tailscale's IPNExtension on the Mac's TS IP
ISSUER = "bardllm-pro"
ORIGIN = os.environ.get("BARDPRO_DEMO_ORIGIN", "http://localhost:5173")
IMAGE = os.environ.get("BARDPRO_AGENT_IMAGE", "bardpro-agent:demo")


def _mint(secret: str, sub: str) -> str:
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": sub, "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(days=1)},
        secret,
        algorithm="HS256",
    )


def _tailscale_ip() -> str:
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip().splitlines()[0]
    except Exception:
        return os.environ.get("BARDPRO_MAC_TS_IP", "<this-mac-tailscale-ip>")


def _serve(app, port: int) -> None:
    cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True).start()


def _run_cmd(
    agent_id: str, ts_ip: str, mac_ip: str, secret: str, port: int, caps: str, gpu: str
) -> str:
    # Default-deny runtime (post-demo tightening): drop all capabilities, no
    # privilege escalation, read-only rootfs (+ tmpfs for /tmp), bounded pids.
    # Plain HTTP over Tailscale needs the explicit BARDPRO_ALLOW_INSECURE_HTTP
    # opt-in — the config layer fails fast without it.
    return (
        f"podman run -d --name {agent_id} --network host \\\n"
        f"  --cap-drop=all --security-opt=no-new-privileges \\\n"
        f"  --read-only --tmpfs /tmp --pids-limit=512 \\\n"
        f"  -e BARDPRO_JWT_SECRET={secret} \\\n"
        f"  -e BARDPRO_SELF_REGISTER=true -e BARDPRO_REGISTRY_SCHEME=http \\\n"
        f"  -e BARDPRO_ALLOW_INSECURE_HTTP=true \\\n"
        f"  -e BARDPRO_REGISTRY_HOST={mac_ip} -e BARDPRO_REGISTRY_PORT={REGISTRY_PORT} \\\n"
        f"  -e BARDPRO_AGENT_ID={agent_id} -e BARDPRO_AGENT_PORT={port} \\\n"
        f"  -e BARDPRO_ADVERTISED_ADDRESS={ts_ip}:{port} \\\n"
        f"  -e BARDPRO_CAPABILITIES='{caps}' \\\n"
        f"  -e BARDPRO_POWER_PROFILE_PATH=/profile.yaml \\\n"
        f"  -v $PWD/{agent_id}.yaml:/profile.yaml:ro{gpu} \\\n"
        f"  {IMAGE}"
    )


def main() -> int:
    secret = os.environ.get("BARDPRO_JWT_SECRET") or secrets.token_urlsafe(32)
    config = Config(jwt_secret=secret, jwt_issuer=ISSUER)
    verifier = JwtVerifier.from_config(config)
    store = RegistryStore()

    registry_app = create_registry(store, verifier, cors_origins=[ORIGIN])
    router_app = create_router(
        HttpRegistryClient(f"http://127.0.0.1:{REGISTRY_PORT}", verify=False),
        HttpAgentClient(verify=False),
        verifier,
        cors_origins=[ORIGIN],
    )
    _serve(registry_app, REGISTRY_PORT)
    _serve(router_app, ROUTER_PORT)
    time.sleep(0.6)

    mac_ip = _tailscale_ip()
    dash_token = _mint(secret, "demo-console")

    print("== Bard — live demo serve-mode ==\n")
    print(f"Registry : http://{mac_ip}:{REGISTRY_PORT}   (plain HTTP + CORS for {ORIGIN})")
    print(f"Router   : http://{mac_ip}:{ROUTER_PORT}")
    print(f"\nJWT secret (share to every agent): {secret}")
    print("\nDashboard .env.local (clients/demo-console):")
    print(f"  VITE_REGISTRY_BASE=http://{mac_ip}:{REGISTRY_PORT}")
    print(f"  VITE_ROUTER_BASE=http://{mac_ip}:{ROUTER_PORT}")
    print(f"  VITE_TOKEN={dash_token}")
    print("\n--- run the GPU node (gx10, NVIDIA GB10) ---")
    print(
        _run_cmd(
            "gx10-gb10",
            # Resolvable hostname by default (MagicDNS/mDNS), never a baked Tailnet IP
            # that won't route off-tailnet; override with BARDPRO_GX10_IP.
            os.environ.get("BARDPRO_GX10_IP", "gx10"),
            mac_ip,
            secret,
            8451,
            "gpu,llm",
            " --device nvidia.com/gpu=all",
        )
    )
    print("\n--- run the laptop node (this Mac) ---")
    print(_run_cmd("mac-laptop", mac_ip, mac_ip, secret, 8452, "llm", ""))
    print("\nServing. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
