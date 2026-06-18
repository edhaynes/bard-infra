"""End-to-end local smoke test on real localhost TLS (macOS/Linux/Windows).

Starts Registry, Agent, and Router as three real uvicorn HTTPS servers on
localhost, registers the agent, mints a JWT, sends a text message through the
Router, and prints the round trip. This is the "running on the Mac" proof —
real sockets + TLS, not the in-process TestClient.

    uv run python scripts/smoke_local.py
"""

from __future__ import annotations

import datetime as _dt
import os
import secrets
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
from agent.engine import make_engine  # noqa: E402
from common.auth import JwtVerifier  # noqa: E402
from common.config import Config  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.store import RegistryStore  # noqa: E402
from router.app import create_app as create_router  # noqa: E402
from router.clients import HttpAgentClient, HttpRegistryClient  # noqa: E402

REGISTRY_PORT = 8081
AGENT_PORT = 8444
ROUTER_PORT = 8443
ISSUER = "bardllm-pro"


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


def main() -> int:
    secret = secrets.token_urlsafe(32)
    # Backend is env-driven so the same smoke proves either the echo path or a
    # real co-located llama.cpp server (start one separately and point
    # BARDPRO_LLAMA_BASE_URL at it). Defaults to echo — unchanged behaviour.
    backend = os.environ.get("BARDPRO_INFERENCE_BACKEND", "echo")
    config = Config(
        jwt_secret=secret,
        jwt_issuer=ISSUER,
        agent_id="agent-local",
        inference_backend=backend,
        llama_base_url=os.environ.get("BARDPRO_LLAMA_BASE_URL", "http://127.0.0.1:8080/v1"),
        llama_model=os.environ.get("BARDPRO_LLAMA_MODEL", "local-gguf"),
    )
    verifier = JwtVerifier.from_config(config)

    tmp = Path(tempfile.mkdtemp(prefix="bardpro-smoke-"))
    ca = trustme.CA()
    leaf = ca.issue_cert("127.0.0.1", "localhost")
    cert, key, ca_pem = tmp / "cert.pem", tmp / "key.pem", tmp / "ca.pem"
    leaf.cert_chain_pems[0].write_to_path(str(cert))
    leaf.private_key_pem.write_to_path(str(key))
    ca.cert_pem.write_to_path(str(ca_pem))
    verify = str(ca_pem)

    registry_app = create_registry(RegistryStore(tmp / "state.json"), verifier)
    agent_app = create_agent(make_engine(config), verifier)
    router_app = create_router(
        HttpRegistryClient(f"https://127.0.0.1:{REGISTRY_PORT}", verify=verify),
        HttpAgentClient(verify=verify),
        verifier,
    )

    servers = [
        _serve(registry_app, REGISTRY_PORT, cert, key),
        _serve(agent_app, AGENT_PORT, cert, key),
        _serve(router_app, ROUTER_PORT, cert, key),
    ]
    try:
        _wait_started(servers)
        token = _mint(secret)
        auth = {"Authorization": f"Bearer {token}"}

        reg = httpx.post(
            f"https://127.0.0.1:{REGISTRY_PORT}/register",
            json={"agentId": config.agent_id, "address": f"127.0.0.1:{AGENT_PORT}"},
            headers=auth,
            verify=verify,
        )
        print(f"register -> {reg.status_code} {reg.json()}")

        msg = httpx.post(
            f"https://127.0.0.1:{ROUTER_PORT}/v1/message",
            json={
                "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
                "type": "text",
                "content": "what is the price of bitcoin?",
                "metadata": {"targetAgent": config.agent_id, "authToken": token},
            },
            verify=verify,
        )
        body = msg.json()
        print(f"message  -> {msg.status_code} {body}")

        # echo asserts the exact reply; a real model just needs a non-empty answer.
        if backend == "echo":
            ok = (
                msg.status_code == 200
                and body.get("content") == "echo: what is the price of bitcoin?"
            )
        else:
            ok = msg.status_code == 200 and bool(body.get("content"))
        print("\nSMOKE: PASS ✅" if ok else "\nSMOKE: FAIL ❌")
        return 0 if ok else 1
    finally:
        for server in servers:
            server.should_exit = True
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
