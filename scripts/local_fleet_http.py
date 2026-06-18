"""Persistent all-HTTP local fleet for client/device testing (no TLS, no Podman).

Stands up Registry + Agent + Router as three real uvicorn servers over **plain
HTTP**, bound to 0.0.0.0 so an Android emulator/device (or any LAN client) can
reach them, registers the agent (echo backend), mints a JWT, prints the
connection details + Android wiring recipe, and then **stays up** until Ctrl-C.

This fills the gap the other scripts leave: smoke_local.py and demo_fleet.py are
one-shot TLS proofs that tear down at the end, and demo_serve.py runs only
Registry+Router (agents are expected to be Podman containers). For wiring the
Flutter client to a local fleet (bug #60/#61) you need all three services, over
HTTP, network-reachable, and persistent — that's this.

Operational tooling, not product logic — excluded from coverage like the other
server entrypoints.

    uv run python scripts/local_fleet_http.py

Ports default to the client's documented defaults (Router 8080, Registry 8081),
overridable via BARDPRO_ROUTER_PORT / BARDPRO_REGISTRY_PORT / BARDPRO_AGENT_PORT.
"""

from __future__ import annotations

import datetime as _dt
import os
import secrets
import sys
import threading
import time
from pathlib import Path

import httpx
import jwt
import uvicorn

# Make the package root importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.app import create_app as create_agent  # noqa: E402
from agent.engine import make_engine  # noqa: E402
from common.auth import JwtVerifier  # noqa: E402
from common.config import Config  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.store import RegistryStore  # noqa: E402
from router.app import create_app as create_router  # noqa: E402
from router.clients import HttpAgentClient, HttpRegistryClient  # noqa: E402

REGISTRY_PORT = int(os.environ.get("BARDPRO_REGISTRY_PORT", "8081"))
ROUTER_PORT = int(os.environ.get("BARDPRO_ROUTER_PORT", "8080"))
AGENT_PORT = int(os.environ.get("BARDPRO_AGENT_PORT", "8444"))
# Re-register interval; must stay well under the Registry TTL (agent_ttl_s, 45s)
# so the agent never ages out to "stale" while the fleet is up.
HEARTBEAT_INTERVAL_S = float(os.environ.get("BARDPRO_HEARTBEAT_INTERVAL_S", "15"))
ISSUER = "bardllm-pro"
AGENT_ID = os.environ.get("BARDPRO_AGENT_ID", "agent-local")
# CORS for the Flutter web target / dashboards; "*" is fine for a local dev fleet.
ORIGIN = os.environ.get("BARDPRO_LOCAL_ORIGIN", "*")


def _mint(secret: str, sub: str) -> str:
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": sub, "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(days=1)},
        secret,
        algorithm="HS256",
    )


def _serve(app, port: int) -> uvicorn.Server:
    cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def _wait_started(servers: list[uvicorn.Server], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    for server in servers:
        while not server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("a server did not start in time")
            time.sleep(0.05)


def main() -> int:
    secret = os.environ.get("BARDPRO_JWT_SECRET") or secrets.token_urlsafe(32)
    backend = os.environ.get("BARDPRO_INFERENCE_BACKEND", "echo")
    config = Config(
        jwt_secret=secret,
        jwt_issuer=ISSUER,
        agent_id=AGENT_ID,
        inference_backend=backend,
    )
    verifier = JwtVerifier.from_config(config)

    registry_app = create_registry(RegistryStore(), verifier, cors_origins=[ORIGIN])
    agent_app = create_agent(make_engine(config), verifier)
    router_app = create_router(
        HttpRegistryClient(f"http://127.0.0.1:{REGISTRY_PORT}", verify=False),
        HttpAgentClient(verify=False),
        verifier,
        cors_origins=[ORIGIN],
    )

    servers = [
        _serve(registry_app, REGISTRY_PORT),
        _serve(agent_app, AGENT_PORT),
        _serve(router_app, ROUTER_PORT),
    ]
    _wait_started(servers)

    token = _mint(secret, "local-client")
    auth = {"Authorization": f"Bearer {token}"}

    # Register with an explicit http:// scheme: the router's agent client
    # (router/clients.py) defaults a schemeless address to https://, which would
    # dial the plain-HTTP agent over TLS and fail. Mirrors demo_up.sh's
    # BARDPRO_ADVERTISED_ADDRESS="http://..." for the same reason.
    def _register() -> httpx.Response:
        return httpx.post(
            f"http://127.0.0.1:{REGISTRY_PORT}/register",
            json={"agentId": AGENT_ID, "address": f"http://127.0.0.1:{AGENT_PORT}"},
            headers=auth,
        )

    reg = _register()
    if reg.status_code != 200:
        print(f"agent registration FAILED -> {reg.status_code} {reg.text}", file=sys.stderr)
        return 1

    # Heartbeat: the Registry ages an agent to "stale" after agent_ttl_s (45s) of
    # no contact, excluding it from placement and from the client's live list. A
    # persistent fleet must keep re-registering — the real agent does this in
    # register.heartbeat_loop; here a daemon thread re-POSTs /register well inside
    # the TTL so the agent stays "active" for as long as the fleet runs.
    def _heartbeat() -> None:
        while True:
            time.sleep(HEARTBEAT_INTERVAL_S)
            try:
                _register()
            except httpx.HTTPError as exc:  # transient; keep the loop alive
                print(f"heartbeat re-register failed: {exc}", file=sys.stderr)

    threading.Thread(target=_heartbeat, daemon=True).start()

    # Prove the full path is live before handing it over (CLAUDE.md §0.16).
    probe = httpx.post(
        f"http://127.0.0.1:{ROUTER_PORT}/v1/message",
        json={
            "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
            "type": "text",
            "content": "ping",
            "metadata": {"targetAgent": AGENT_ID, "authToken": token},
        },
    )
    probe_ok = probe.status_code == 200 and bool(probe.json().get("content"))

    print("== Bard — local all-HTTP fleet ==\n")
    print(f"Registry : http://127.0.0.1:{REGISTRY_PORT}   (GET /agents)")
    print(f"Router   : http://127.0.0.1:{ROUTER_PORT}   (POST /v1/message)")
    print(f"Agent    : http://127.0.0.1:{AGENT_PORT}   (backend={backend}, id={AGENT_ID})")
    print(
        f"\nregister -> {reg.status_code}   round-trip -> "
        f"{probe.status_code} {probe.json().get('content')!r} "
        f"{'✅' if probe_ok else '❌'}"
    )
    print(f"\nBearer token (BARD_AUTH_TOKEN):\n{token}")
    print("\n--- Android client wiring ---")
    print("# A) adb reverse — default 127.0.0.1 URLs work on emulator + USB device:")
    print(f"adb reverse tcp:{ROUTER_PORT} tcp:{ROUTER_PORT}")
    print(f"adb reverse tcp:{REGISTRY_PORT} tcp:{REGISTRY_PORT}")
    print("flutter run -d <device> \\")
    print(f"  --dart-define=BARD_AUTH_TOKEN={token}")
    print("# B) emulator host alias (no adb reverse):")
    print("flutter run -d emulator-5554 \\")
    print(f"  --dart-define=BARD_ROUTER_URL=http://10.0.2.2:{ROUTER_PORT} \\")
    print(f"  --dart-define=BARD_REGISTRY_URL=http://10.0.2.2:{REGISTRY_PORT} \\")
    print(f"  --dart-define=BARD_AUTH_TOKEN={token}")
    if not probe_ok:
        print(
            "\nWARNING: the round-trip probe did not return content — check the logs.",
            file=sys.stderr,
        )
    print("\nServing on 0.0.0.0. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
    finally:
        for server in servers:
            server.should_exit = True
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
