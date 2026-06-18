"""Mesh-free (Tailscale-free) broker smoke on real localhost TLS sockets.

This is the LokNet "single front door" proof (feature #59 / ADR-0013, slice 3):
the agent registers and serves inference **purely over its outbound WebSocket
link** to the Router — it is given **no usable direct route to the Registry**.

Topology (all real uvicorn HTTPS / WSS servers on loopback, not TestClient):

    Registry  (private, loopback bind)      <-- only the Router talks to it
        ^  relayed register/heartbeat
        |
    Router    (public-facing bind, :PORT)   <-- the single front door
        ^  outbound wss /v1/agent-link
        |
    Agent     (BARDPRO_BROKER_ENABLED=true)  --> dials OUT only; its registry
                                                 pointer is a closed blackhole
                                                 port, so registration + infer
                                                 CANNOT use a direct dial.

If the agent shows up in the Registry's /pool and /schedule, and a POST to the
Router's /v1/message returns a real echo completion, then registration and
inference both rode the link with zero inbound reachability and zero direct
Registry route — the Tailscale-free path, proven on real sockets.

    uv run python scripts/smoke_broker.py
"""

from __future__ import annotations

import datetime as _dt
import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import jwt
import trustme
import uvicorn

# Make the package root importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.app import create_app as create_agent  # noqa: E402
from agent.broker import broker_loop  # noqa: E402
from agent.engine import make_engine  # noqa: E402
from common.auth import JwtVerifier  # noqa: E402
from common.config import Config  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.store import RegistryStore  # noqa: E402
from router.app import create_app as create_router  # noqa: E402
from router.broker import BrokerLinkManager  # noqa: E402
from router.clients import HttpAgentClient, HttpRegistryClient  # noqa: E402

REGISTRY_PORT = 8091  # private, loopback-only
ROUTER_PORT = 8453  # public front door
AGENT_PORT = 8454  # the agent's own HTTP bind (unused by this proof)
ISSUER = "bardllm-pro"
AGENT_ID = "agent-broker-smoke"
MESSAGE = "what is the price of bitcoin?"
EXPECTED = f"echo: {MESSAGE}"


def _closed_port() -> int:
    """Bind then release a loopback port so nothing is listening on it — the
    agent's "blackhole" Registry pointer. A direct dial here would be refused,
    which is exactly the point: the proof must not depend on it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _mint(secret: str) -> str:
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": "smoke", "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        secret,
        algorithm="HS256",
    )


def _serve(app, port: int, cert: Path, key: Path) -> uvicorn.Server:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def _wait_started(servers: list[uvicorn.Server], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    for server in servers:
        while not server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("server did not start in time")
            time.sleep(0.05)


def _write_power_profile(tmp: Path) -> Path:
    """A minimal valid power profile so the node shows up in /pool's aggregate
    and is a real /schedule candidate."""
    path = tmp / "power.yaml"
    path.write_text(
        "name: broker-smoke-node\ncpus: 4\nmemory: 8g\n",
        encoding="utf-8",
    )
    return path


def _agent_config(secret: str, ca_pem: Path, profile: Path) -> Config:
    """Agent in broker mode with NO usable direct Registry route.

    ``broker_enabled`` + ``self_register`` make the agent register/heartbeat
    over the link; ``registry_host:registry_port`` point at a closed port, so
    if any code path tried a direct dial it would be refused — proving the
    registration rode the link. ``tls_cert_path`` is our throwaway CA so the
    outbound wss handshake to the Router validates.
    """
    return Config(
        jwt_secret=secret,
        jwt_issuer=ISSUER,
        agent_id=AGENT_ID,
        registry_host="127.0.0.1",
        registry_port=_closed_port(),  # blackhole: no direct route
        broker_enabled=True,
        broker_url=f"wss://127.0.0.1:{ROUTER_PORT}/v1/agent-link",
        self_register=True,
        capabilities="cpu,llm",
        power_profile_path=str(profile),
        tls_cert_path=str(ca_pem),
        heartbeat_interval_s=2.0,
        broker_backoff_initial_s=0.2,
        inference_backend="echo",
    )


def _poll(fn, timeout: float = 15.0, interval: float = 0.25):
    """Poll ``fn`` until it returns a truthy value or the deadline passes.

    Registration over the link is asynchronous (handshake -> register frame ->
    relay to the Registry), so we wait for it to land rather than assume it is
    instantaneous."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None


def _registered(reg_url: str, auth: dict, verify: str) -> dict | None:
    """Return the agent's record from /agents once it appears, else None."""
    resp = httpx.get(f"{reg_url}/agents", headers=auth, verify=verify)
    if resp.status_code != 200:
        return None
    for record in resp.json():
        if record.get("agentId") == AGENT_ID:
            return record
    return None


def main() -> int:  # noqa: C901 - linear smoke script, one pass top to bottom
    secret = secrets.token_urlsafe(32)
    base = Config(jwt_secret=secret, jwt_issuer=ISSUER)
    verifier = JwtVerifier.from_config(base)

    tmp = Path(tempfile.mkdtemp(prefix="bardpro-broker-smoke-"))
    ca = trustme.CA()
    leaf = ca.issue_cert("127.0.0.1", "localhost")
    cert, key, ca_pem = tmp / "cert.pem", tmp / "key.pem", tmp / "ca.pem"
    leaf.cert_chain_pems[0].write_to_path(str(cert))
    leaf.private_key_pem.write_to_path(str(key))
    ca.cert_pem.write_to_path(str(ca_pem))
    verify = str(ca_pem)
    profile = _write_power_profile(tmp)

    # Registry stays private (loopback); only the Router holds a client to it.
    registry_app = create_registry(RegistryStore(tmp / "state.json"), verifier)
    registry_url = f"https://127.0.0.1:{REGISTRY_PORT}"
    router_registry = HttpRegistryClient(registry_url, verify=verify)
    # The Router is the single public front door: register/heartbeat relay +
    # the /v1/agent-link WebSocket + /v1/message dispatch all live here.
    broker = BrokerLinkManager(timeout_s=10.0)
    router_app = create_router(
        router_registry,
        HttpAgentClient(verify=verify),
        verifier,
        broker=broker,
    )

    agent_config = _agent_config(secret, ca_pem, profile)
    agent_engine = make_engine(agent_config)
    agent_verifier = JwtVerifier.from_config(agent_config)
    # Mirror agent/main.py broker wiring: the outbound link is the only
    # registration + inference path. No direct heartbeat is started.
    agent_app = create_agent(
        agent_engine,
        agent_verifier,
        broker=lambda: broker_loop(agent_config, agent_engine, agent_verifier),
        backend_name="echo",
    )

    servers = [
        _serve(registry_app, REGISTRY_PORT, cert, key),
        _serve(router_app, ROUTER_PORT, cert, key),
        _serve(agent_app, AGENT_PORT, cert, key),
    ]
    ok = False
    try:
        _wait_started(servers)
        token = _mint(secret)
        auth = {"Authorization": f"Bearer {token}"}

        # 1. The agent registered OVER THE LINK (no direct Registry route exists).
        record = _poll(lambda: _registered(registry_url, auth, verify))
        if record is None:
            print("agent never appeared in the Registry over the link")
            return 1
        address = record.get("address", "")
        print(f"registered (over link) -> {AGENT_ID} address={address!r}")

        # 2. /pool sees the node (its power profile aggregated in).
        pool = httpx.get(f"{registry_url}/pool", headers=auth, verify=verify).json()
        print(f"pool      -> {pool}")

        # 3. /schedule picks it.
        sched = httpx.get(f"{registry_url}/schedule", headers=auth, verify=verify).json()
        print(f"schedule  -> {sched.get('agentId')!r}")

        # 4. Inference round-trips the Router -> link -> agent engine -> back.
        msg = httpx.post(
            f"https://127.0.0.1:{ROUTER_PORT}/v1/message",
            json={
                "id": "b40c9e1f-2a7d-4c61-8e3b-9f0a1b2c3d4e",
                "type": "text",
                "content": MESSAGE,
                "metadata": {"targetAgent": AGENT_ID, "authToken": token},
            },
            verify=verify,
        )
        body = msg.json()
        print(f"message   -> {msg.status_code} {body}")

        ok = (
            address.startswith("broker://")
            and pool.get("nodes", 0) >= 1
            and sched.get("agentId") == AGENT_ID
            and msg.status_code == 200
            and body.get("content") == EXPECTED
        )
        print("\nBROKER SMOKE: PASS" if ok else "\nBROKER SMOKE: FAIL")
        return 0 if ok else 1
    finally:
        for server in servers:
            server.should_exit = True
        time.sleep(0.3)


if __name__ == "__main__":
    raise SystemExit(main())
