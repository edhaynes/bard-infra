r"""Two-node LLM routing smoke: the Router inferences REAL models across TWO
broker-linked nodes over bardnet (LokNet, ADR-0013), on real localhost sockets.

This is the "it works" proof Eddie asked for: an LLM router inferencing over two
linked nodes with suitable small workloads. Both agents dial OUT to the Router
over a WebSocket link (no inbound ports, no direct Registry route), each fronts a
different small Ollama model through the OpenAI-compatible `LlamaCppEngine`, and a
client routes a request to EACH node by name. Because the Router dispatches
`/v1/message` down the live link for `metadata.targetAgent` (router/app.py) and the
engine stamps `metadata.agentId = config.agent_id`, a completion that comes back
tagged with the targeted node proves the request rode that node's link and ran on
that node's model.

Topology (real uvicorn HTTPS/WSS on loopback, not TestClient):

    Registry (private)  <-- Router only
        ^ relayed register/heartbeat over the link
    Router (public :ROUTER_PORT)  <-- single front door, /v1/agent-link + /v1/message
        ^ outbound wss                     ^ outbound wss
    node-a (Ollama model A)            node-b (Ollama model B)
        \--> http Ollama /v1 -->/          \--> http Ollama /v1 -->/

Prereqs: Ollama running on :11434 with the two models pulled. Small models are the
point ("suitable small workloads"): defaults are the tiny Vulcan models.

    uv run python scripts/smoke_two_node_infer.py

Env overrides:
    SMOKE_OLLAMA_URL     (default http://127.0.0.1:11434/v1)
    SMOKE_NODE_A_MODEL   (default VulcanTerra1.1.0:200M)
    SMOKE_NODE_B_MODEL   (default VulcanMega0.1.0:110M)
"""

from __future__ import annotations

import datetime as _dt
import os
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
ROUTER_PORT = 8463  # public front door
ISSUER = "bardllm-pro"

OLLAMA_URL = os.environ.get("SMOKE_OLLAMA_URL", "http://127.0.0.1:11434/v1")
# Two DIFFERENT small models so distinct routing is visible. Tiny by design —
# "suitable small workloads that can be routed."
NODES = [
    ("node-a", os.environ.get("SMOKE_NODE_A_MODEL", "VulcanTerra1.1.0:200M"), 8465),
    ("node-b", os.environ.get("SMOKE_NODE_B_MODEL", "VulcanMega0.1.0:110M"), 8466),
]
PROMPT = "Reply with a single short sentence."


def _closed_port() -> int:
    """A bound-then-released loopback port: the agent's blackhole Registry
    pointer, so a direct dial would be refused and registration must ride the
    link."""
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


def _write_power_profile(tmp: Path, name: str) -> Path:
    path = tmp / f"power-{name}.yaml"
    path.write_text(f"name: {name}\ncpus: 4\nmemory: 8g\n", encoding="utf-8")
    return path


def _agent_config(agent_id: str, model: str, secret: str, ca_pem: Path, profile: Path) -> Config:
    """A broker-mode agent fronting a small Ollama model through the
    OpenAI-compatible LlamaCppEngine, with NO usable direct Registry route."""
    return Config(
        jwt_secret=secret,
        jwt_issuer=ISSUER,
        agent_id=agent_id,
        registry_host="127.0.0.1",
        registry_port=_closed_port(),  # blackhole: registration must ride the link
        broker_enabled=True,
        broker_url=f"wss://127.0.0.1:{ROUTER_PORT}/v1/agent-link",
        self_register=True,
        capabilities="cpu,llm",
        power_profile_path=str(profile),
        tls_cert_path=str(ca_pem),
        heartbeat_interval_s=2.0,
        broker_backoff_initial_s=0.2,
        inference_backend="llamacpp",
        llama_base_url=OLLAMA_URL,
        llama_model=model,
    )


def _poll(fn, timeout: float = 15.0, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None


def _linked(broker: BrokerLinkManager, agent_id: str):
    return lambda: broker.has_link(agent_id)


def _preflight_ollama() -> bool:
    """Fail fast (coding-rules §11) if Ollama or a model is missing, and warm each
    model so the first timed dispatch isn't a cold-load."""
    try:
        for agent_id, model, _ in NODES:
            r = httpx.post(
                f"{OLLAMA_URL}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                timeout=120.0,
            )
            if r.status_code != 200:
                print(f"PREFLIGHT FAIL: {model} -> {r.status_code} {r.text[:200]}")
                return False
            print(f"preflight -> {agent_id}: {model} warm ({r.status_code})")
    except httpx.HTTPError as exc:
        print(f"PREFLIGHT FAIL: cannot reach Ollama at {OLLAMA_URL}: {exc}")
        return False
    return True


def main() -> int:  # noqa: C901 - linear smoke script, one pass top to bottom
    if not _preflight_ollama():
        return 1

    secret = secrets.token_urlsafe(32)
    base = Config(jwt_secret=secret, jwt_issuer=ISSUER)
    verifier = JwtVerifier.from_config(base)

    tmp = Path(tempfile.mkdtemp(prefix="bardpro-two-node-infer-"))
    ca = trustme.CA()
    leaf = ca.issue_cert("127.0.0.1", "localhost")
    cert, key, ca_pem = tmp / "cert.pem", tmp / "key.pem", tmp / "ca.pem"
    leaf.cert_chain_pems[0].write_to_path(str(cert))
    leaf.private_key_pem.write_to_path(str(key))
    ca.cert_pem.write_to_path(str(ca_pem))
    verify = str(ca_pem)

    # Registry stays private; only the Router holds a client to it. The Router is
    # the single front door: /v1/agent-link links + /v1/message dispatch.
    registry_app = create_registry(RegistryStore(tmp / "state.json"), verifier)
    registry_url = f"https://127.0.0.1:{REGISTRY_PORT}"
    router_registry = HttpRegistryClient(registry_url, verify=verify)
    broker = BrokerLinkManager(timeout_s=60.0)  # generous: real model inference
    router_app = create_router(
        router_registry, HttpAgentClient(verify=verify), verifier, broker=broker
    )

    servers = [
        _serve(registry_app, REGISTRY_PORT, cert, key),
        _serve(router_app, ROUTER_PORT, cert, key),
    ]
    # Two broker-mode agents, each a different small model.
    for agent_id, model, port in NODES:
        profile = _write_power_profile(tmp, agent_id)
        cfg = _agent_config(agent_id, model, secret, ca_pem, profile)
        engine = make_engine(cfg)
        agent_verifier = JwtVerifier.from_config(cfg)
        app = create_agent(
            engine,
            agent_verifier,
            broker=lambda c=cfg, e=engine, v=agent_verifier: broker_loop(c, e, v),
            backend_name="llamacpp",
        )
        servers.append(_serve(app, port, cert, key))

    ok = False
    try:
        _wait_started(servers)
        token = _mint(secret)

        # 1. Both nodes establish a live link to the Router.
        for agent_id, _, _ in NODES:
            if _poll(_linked(broker, agent_id), timeout=20.0) is None:
                print(f"{agent_id} never established a broker link")
                return 1
            print(f"linked    -> {agent_id}")

        # 2. Route a real inference to EACH node by name; the completion must come
        #    back tagged with the targeted node (proves it rode that node's link
        #    and ran on that node's model).
        results = {}
        for agent_id, model, _ in NODES:
            resp = httpx.post(
                f"https://127.0.0.1:{ROUTER_PORT}/v1/message",
                json={
                    "id": f"infer-{agent_id}",
                    "type": "text",
                    "content": PROMPT,
                    "metadata": {"targetAgent": agent_id, "authToken": token},
                },
                verify=verify,
                timeout=90.0,
            )
            body = resp.json()
            served_by = body.get("metadata", {}).get("agentId")
            content = (body.get("content") or "").strip()
            results[agent_id] = (resp.status_code, served_by, content)
            print(
                f"route -> {agent_id} ({model}): {resp.status_code} "
                f"servedBy={served_by!r} content={content[:80]!r}"
            )

        ok = all(
            status == 200 and served_by == agent_id and content
            for agent_id, (status, served_by, content) in results.items()
        )
        print("\nTWO-NODE INFER SMOKE: PASS" if ok else "\nTWO-NODE INFER SMOKE: FAIL")
        return 0 if ok else 1
    finally:
        for server in servers:
            server.should_exit = True
        time.sleep(0.3)


if __name__ == "__main__":
    raise SystemExit(main())
