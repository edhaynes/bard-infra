"""Sprint B6 smoke — the full console-manage loop on real localhost sockets.

The feature #64 done-signal, end to end against a locally running
Registry + Router + Agent (real uvicorn servers on loopback, not TestClient):

    enroll  -> the device lands "pending" and shows in GET /fleet
    approve -> via the console's API path (POST /devices/{id}/approve,
               manager bearer) — the one-time per-device secret comes back
    serve   -> the device boots its agent with that secret and links
               OUTBOUND to the Router (broker, ADR-0013); a relay through
               /v1/message with the device's own token returns a real
               completion (per-device relay auth, Sprint B4)
    rename / workgroup -> console paths; GET /fleet reflects both
    revoke  -> via the console path; the SAME device token is now rejected
               at the Router (reload-on-read store, no restart)
    audit   -> GET /audit lists approve/rename/workgroup/revoke, newest
               first, with the manager token's subject as the actor

Plain HTTP/WS on loopback: this proof is about the manage loop, not
transport (scripts/smoke_broker.py owns the TLS/WSS front-door proof).

    uv run python scripts/smoke_console_manage.py
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
import uvicorn

# Make the package root importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.app import create_app as create_agent  # noqa: E402
from agent.broker import broker_loop  # noqa: E402
from agent.engine import EchoEngine  # noqa: E402
from common.auth import JwtVerifier  # noqa: E402
from common.config import Config  # noqa: E402
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.audit_log import AuditLog  # noqa: E402
from registry.device_store import DeviceStore  # noqa: E402
from registry.store import RegistryStore  # noqa: E402
from router.app import create_app as create_router  # noqa: E402
from router.broker import BrokerLinkManager  # noqa: E402
from router.clients import HttpAgentClient, HttpRegistryClient  # noqa: E402

ISSUER = "bardllm-pro"
DEVICE_ID = "smoke-front-desk"
MESSAGE = "hello from the front desk"
EXPECTED = f"echo: {MESSAGE}"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _mint_manager(secret: str) -> str:
    """The console's manager bearer (sub = the audit actor)."""
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": "manager-eddie", "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        secret,
        algorithm="HS256",
    )


def _serve(app, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
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


def _msg_body(token: str) -> dict:
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "type": "text",
        "content": MESSAGE,
        "metadata": {"targetAgent": DEVICE_ID, "authToken": token},
    }


def _step(ok: bool, label: str) -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def main() -> int:  # noqa: C901 - linear smoke script, one pass top to bottom
    fleet_secret = secrets.token_urlsafe(32)
    join_secret = secrets.token_urlsafe(32)
    tmp = Path(tempfile.mkdtemp(prefix="bardpro-console-smoke-"))
    device_state = tmp / "devices.json"

    registry_port, router_port, agent_port = _free_port(), _free_port(), _free_port()
    reg_url = f"http://127.0.0.1:{registry_port}"
    router_url = f"http://127.0.0.1:{router_port}"

    fleet_verifier = JwtVerifier(fleet_secret, "HS256", ISSUER)
    # The Registry writes this store; Router/Agent read the same file with
    # reload_on_read so a console revoke takes effect on the next request.
    registry_device_store = DeviceStore(device_state, join_token_secret=join_secret, issuer=ISSUER)
    audit_log = AuditLog(tmp / "audit-log.jsonl")
    registry_app = create_registry(
        RegistryStore(tmp / "registry-state.json"),
        fleet_verifier,
        device_store=registry_device_store,
        audit_log=audit_log,
    )

    def _relay_verifier() -> FleetOrDeviceVerifier:
        reader = DeviceStore(
            device_state, join_token_secret=join_secret, issuer=ISSUER, reload_on_read=True
        )
        return FleetOrDeviceVerifier(fleet_verifier, PerDeviceVerifier(reader, issuer=ISSUER))

    # The Router is the front door: the device's agent dials OUT to its
    # /v1/agent-link and serves down that link (ADR-0013) — exactly how an
    # enrolled device with no inbound reachability serves in the product.
    broker = BrokerLinkManager(timeout_s=10.0)
    router_app = create_router(
        HttpRegistryClient(reg_url), HttpAgentClient(), _relay_verifier(), broker=broker
    )

    servers = [
        _serve(registry_app, registry_port),
        _serve(router_app, router_port),
    ]
    _wait_started(servers)
    print(f"registry={reg_url}  router={router_url}")

    manager = {"Authorization": f"Bearer {_mint_manager(fleet_secret)}"}
    ok = True

    # 1. Enroll: a fresh device presents its join token, lands pending.
    join_token = registry_device_store.issue_join_token(ttl_s=600)
    r = httpx.post(
        f"{reg_url}/enroll",
        json={"deviceId": DEVICE_ID, "joinToken": join_token, "label": "Front desk PC"},
    )
    ok &= _step(
        r.status_code == 200 and r.json()["device"]["state"] == "pending",
        "enroll -> pending",
    )

    # 2. The console's fleet view shows it, waiting for approval.
    rows = {d["id"]: d for d in httpx.get(f"{reg_url}/fleet", headers=manager).json()["devices"]}
    ok &= _step(rows[DEVICE_ID]["enrollment"] == "pending", "GET /fleet shows the pending device")

    # 3. Approve via the console's API path; the one-time secret comes back.
    r = httpx.post(f"{reg_url}/devices/{DEVICE_ID}/approve", headers=manager)
    device_secret = r.json().get("deviceSecret", "")
    ok &= _step(
        r.status_code == 200 and r.json()["device"]["state"] == "active" and bool(device_secret),
        "console approve -> active + one-time secret",
    )

    # 4. The device serves: boot its agent with the freshly-disclosed secret.
    #    It links OUTBOUND to the Router (broker hello signed with the device
    #    credential), then a relay through /v1/message with the device's OWN
    #    token returns a real completion (per-device relay auth, Sprint B4).
    agent_config = Config(
        jwt_secret=fleet_secret,
        jwt_issuer=ISSUER,
        agent_id=DEVICE_ID,
        device_identity_enabled=True,
        device_secret=device_secret,
        broker_enabled=True,
        broker_url=f"ws://127.0.0.1:{router_port}/v1/agent-link",
        allow_insecure_http=True,  # loopback smoke; TLS is smoke_broker's proof
        broker_backoff_initial_s=0.2,
    )
    agent_engine = EchoEngine(DEVICE_ID)
    agent_verifier = _relay_verifier()
    agent_app = create_agent(
        agent_engine,
        agent_verifier,
        broker=lambda: broker_loop(agent_config, agent_engine, agent_verifier),
        backend_name="echo",
    )
    agent_server = _serve(agent_app, agent_port)
    _wait_started([agent_server])

    device_token = registry_device_store.mint_device_token(DEVICE_ID, device_secret, ttl_s=600)
    deadline = time.monotonic() + 15.0
    r = None
    while time.monotonic() < deadline:  # the outbound link lands asynchronously
        r = httpx.post(f"{router_url}/v1/message", json=_msg_body(device_token), timeout=10.0)
        if r.status_code == 200:
            break
        time.sleep(0.25)
    ok &= _step(
        r is not None and r.status_code == 200 and r.json().get("content") == EXPECTED,
        "approved device serves over its outbound link via the Router",
    )

    # 5. Rename + workgroup via the console paths; /fleet reflects both.
    httpx.post(
        f"{reg_url}/devices/{DEVICE_ID}/rename", json={"label": "Reception PC"}, headers=manager
    )
    httpx.post(
        f"{reg_url}/devices/{DEVICE_ID}/workgroup", json={"name": "Front office"}, headers=manager
    )
    rows = {d["id"]: d for d in httpx.get(f"{reg_url}/fleet", headers=manager).json()["devices"]}
    row = rows[DEVICE_ID]
    ok &= _step(
        row["label"] == "Reception PC" and (row["workgroup"] or {}).get("name") == "Front office",
        "rename + workgroup show in GET /fleet",
    )

    # 6. Revoke via the console path; the SAME token is rejected at the Router.
    r = httpx.post(f"{reg_url}/devices/{DEVICE_ID}/revoke", headers=manager)
    ok &= _step(
        r.status_code == 200 and r.json()["device"]["state"] == "revoked",
        "console revoke -> revoked",
    )
    r = httpx.post(f"{router_url}/v1/message", json=_msg_body(device_token), timeout=10.0)
    ok &= _step(r.status_code in (401, 403), "revoked device's relay is rejected")

    # 7. The audit trail names the manager on every action, newest first.
    entries = httpx.get(f"{reg_url}/audit", headers=manager).json()["entries"]
    actions = [e["action"] for e in entries]
    ok &= _step(
        actions == ["revoke", "workgroup", "rename", "approve"]
        and all(e["actor"] == "manager-eddie" for e in entries)
        and all(e["deviceId"] == DEVICE_ID for e in entries),
        "GET /audit lists approve/rename/workgroup/revoke with the actor",
    )

    print("SMOKE PASS" if ok else "SMOKE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
