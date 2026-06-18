"""Demo fleet harness — stranded-compute pool, end to end (Chris Wright demo).

Stands up a real multi-node fleet on localhost TLS — Registry + Router + N
heterogeneous Agents (distinct power profiles) — then exercises the whole
Phase-1 chain the demo dashboard reads:

    register-with-capability  ->  GET /pool  ->  GET /schedule  ->  POST /v1/message

This is the integration proof for the demo backbone (real sockets + TLS, real
registration, real aggregation, real placement, real completion). Run it:

    uv run python scripts/demo_fleet.py            # echo backend (fast, reliable)
    BARDPRO_INFERENCE_BACKEND=llamacpp uv run python scripts/demo_fleet.py  # real model

Operational tooling, not product logic — excluded from coverage like the other
server entrypoints.
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
ROUTER_PORT = 8443
ISSUER = "bardllm-pro"

# Heterogeneous fleet personas — real nodes, distinct advertised capacity. The
# GPU workstation is where a GPU-preferred job should land.
FLEET = [
    {
        "agentId": "gpu-workstation",
        "port": 8451,
        "capabilities": ["gpu", "llm"],
        "powerProfile": {"name": "gpu-workstation", "cpus": 16, "memory": "64g", "gpus": "all"},
    },
    {
        "agentId": "dev-laptop",
        "port": 8452,
        "capabilities": ["llm"],
        "powerProfile": {"name": "dev-laptop", "cpus": 8, "memory": "16g", "gpus": None},
    },
    {
        "agentId": "storage-node",
        "port": 8453,
        "capabilities": ["storage"],
        "powerProfile": {"name": "storage-node", "cpus": 4, "memory": "8g", "gpus": None},
    },
    {
        "agentId": "edge-box",
        "port": 8454,
        "capabilities": ["llm"],
        "powerProfile": {"name": "edge-box", "cpus": 4, "memory": "4g", "gpus": None},
    },
]


def _mint(secret: str) -> str:
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": "demo", "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
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


def _fmt_gb(num_bytes: int) -> str:
    return f"{num_bytes / 1024**3:.0f} GiB"


def main() -> int:
    secret = secrets.token_urlsafe(32)
    backend = os.environ.get("BARDPRO_INFERENCE_BACKEND", "echo")
    base = Config(jwt_secret=secret, jwt_issuer=ISSUER)
    verifier = JwtVerifier.from_config(base)

    tmp = Path(tempfile.mkdtemp(prefix="bardpro-demo-"))
    ca = trustme.CA()
    leaf = ca.issue_cert("127.0.0.1", "localhost")
    cert, key, ca_pem = tmp / "cert.pem", tmp / "key.pem", tmp / "ca.pem"
    leaf.cert_chain_pems[0].write_to_path(str(cert))
    leaf.private_key_pem.write_to_path(str(key))
    ca.cert_pem.write_to_path(str(ca_pem))
    verify = str(ca_pem)

    store = RegistryStore()
    registry_app = create_registry(store, verifier)
    router_app = create_router(
        HttpRegistryClient(f"https://127.0.0.1:{REGISTRY_PORT}", verify=verify),
        HttpAgentClient(verify=verify),
        verifier,
    )
    servers = [
        _serve(registry_app, REGISTRY_PORT, cert, key),
        _serve(router_app, ROUTER_PORT, cert, key),
    ]
    for node in FLEET:
        cfg = Config(
            jwt_secret=secret,
            jwt_issuer=ISSUER,
            agent_id=node["agentId"],
            inference_backend=backend,
        )
        servers.append(_serve(create_agent(make_engine(cfg), verifier), node["port"], cert, key))

    try:
        _wait_started(servers)
        token = _mint(secret)
        auth = {"Authorization": f"Bearer {token}"}

        print(f"== Bard — stranded-compute fleet ({backend} backend) ==\n")
        for node in FLEET:
            reg = httpx.post(
                f"https://127.0.0.1:{REGISTRY_PORT}/register",
                json={
                    "agentId": node["agentId"],
                    "address": f"127.0.0.1:{node['port']}",
                    "capabilities": node["capabilities"],
                    "powerProfile": node["powerProfile"],
                },
                headers=auth,
                verify=verify,
            )
            pp = node["powerProfile"]
            gpu = pp["gpus"] or "—"
            print(
                f"  [{reg.status_code}] {node['agentId']:<16} "
                f"{pp['cpus']:>2} cpu  {pp['memory']:>4}  gpu={gpu}"
            )

        pool = httpx.get(
            f"https://127.0.0.1:{REGISTRY_PORT}/pool", headers=auth, verify=verify
        ).json()
        print(
            f"\nPOOL: {pool['nodes']} nodes · {pool['cpus']:.0f} cpus · "
            f"{_fmt_gb(pool['memoryBytes'])} · {pool['gpuNodes']} GPU node(s)"
        )

        chosen = httpx.get(
            f"https://127.0.0.1:{REGISTRY_PORT}/schedule",
            params={"gpu": "true"},
            headers=auth,
            verify=verify,
        ).json()
        print(f"SCHEDULE (gpu-preferred) -> {chosen['agentId']} @ {chosen['address']}")

        msg = httpx.post(
            f"https://127.0.0.1:{ROUTER_PORT}/v1/message",
            json={
                "id": "demo-1",
                "type": "text",
                "content": "Summarize Red Hat's open hybrid cloud strategy in one sentence.",
                "metadata": {"targetAgent": chosen["agentId"], "authToken": token},
            },
            verify=verify,
        )
        body = msg.json()
        ok = msg.status_code == 200 and bool(body.get("content"))
        print(f"JOB -> {chosen['agentId']} [{msg.status_code}]: {body.get('content')!r}")
        print("\nDEMO FLEET: PASS ✅" if ok else "\nDEMO FLEET: FAIL ❌")
        return 0 if ok else 1
    finally:
        for server in servers:
            server.should_exit = True
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
