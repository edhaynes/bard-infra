"""Sprint B8 smoke — the plugin-manage loop on a real localhost socket.

The feature #65 done-signal, end to end against a locally running Registry
(real uvicorn server on loopback, not TestClient), driving the same
control-plane endpoints the console's Plugins pane uses:

    catalog -> GET /plugins lists BOTH catalog entries (Squawk Box + SSH),
               loaded from the example manifests and validated against the
               frozen plugin-manifest contract at startup
    enable  -> Squawk Box turned on for a WORKGROUP (config travels with
               the enable and is validated against the manifest's own
               configSchema); a config-less enable of Squawk Box is REFUSED
               (400 — its schema requires "channel": fail fast)
    round-trip -> GET /plugins reflects the enable on the next read
    config  -> PUT then GET /plugins/{id}/config round-trips the settings
    health  -> a device reports SSH plugin health; GET /plugins shows it
    disable -> Squawk Box turned off; GET /plugins reflects it
    audit   -> GET /audit lists plugin-enable/plugin-config/plugin-disable,
               newest first, with the manager token's subject as the actor

Plain HTTP on loopback: this proof is about the manage loop, not transport
(scripts/smoke_broker.py owns the TLS/WSS front-door proof).

    uv run python scripts/smoke_plugin_manage.py
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

from common.auth import JwtVerifier  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.audit_log import AuditLog  # noqa: E402
from registry.plugin_store import PluginStore  # noqa: E402
from registry.store import RegistryStore  # noqa: E402

ISSUER = "bardllm-pro"
SQUAWK = "pro.bardllm.squawk-box"
SSH = "pro.bardllm.ssh"
WORKGROUP = "North crew"
CATALOG_DIR = Path(__file__).resolve().parents[1] / "examples" / "plugins"


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


def _wait_started(server: uvicorn.Server, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("server did not start in time")
        time.sleep(0.05)


def _step(ok: bool, label: str) -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def _plugin(view: dict, plugin_id: str) -> dict:
    return next(p for p in view["plugins"] if p["manifest"]["id"] == plugin_id)


def main() -> int:
    fleet_secret = secrets.token_urlsafe(32)
    tmp = Path(tempfile.mkdtemp(prefix="bardpro-plugin-smoke-"))

    registry_port = _free_port()
    reg_url = f"http://127.0.0.1:{registry_port}"

    audit_log = AuditLog(tmp / "audit-log.jsonl")
    plugin_store = PluginStore(CATALOG_DIR, tmp / "plugin-state.json")
    registry_app = create_registry(
        RegistryStore(tmp / "registry-state.json"),
        JwtVerifier(fleet_secret, "HS256", ISSUER),
        audit_log=audit_log,
        plugin_store=plugin_store,
    )
    _wait_started(_serve(registry_app, registry_port))
    print(f"registry={reg_url}")

    manager = {"Authorization": f"Bearer {_mint_manager(fleet_secret)}"}
    ok = True

    # 1. The catalog lists both plugins, loaded from the example manifests.
    view = httpx.get(f"{reg_url}/plugins", headers=manager).json()
    ids = sorted(p["manifest"]["id"] for p in view["plugins"])
    ok &= _step(ids == [SQUAWK, SSH], "GET /plugins lists both catalog entries")

    # 2. Fail fast: enabling Squawk Box with no config is refused — its
    #    manifest's configSchema requires "channel".
    r = httpx.post(
        f"{reg_url}/plugins/{SQUAWK}/enable",
        json={"scope": "workgroup", "target": WORKGROUP},
        headers=manager,
    )
    ok &= _step(
        r.status_code == 400 and "channel" in r.json()["detail"],
        "config-less enable is refused (400, schema names the missing field)",
    )

    # 3. Enable Squawk Box for a workgroup, config travelling with the enable.
    r = httpx.post(
        f"{reg_url}/plugins/{SQUAWK}/enable",
        json={
            "scope": "workgroup",
            "target": WORKGROUP,
            "config": {"channel": "crew-north", "pushToTalk": True},
        },
        headers=manager,
    )
    ok &= _step(
        r.status_code == 200 and r.json()["enabledWorkgroups"][0]["name"] == WORKGROUP,
        "enable Squawk Box for a workgroup (valid config)",
    )

    # 4. The enable state round-trips through a fresh GET /plugins.
    view = httpx.get(f"{reg_url}/plugins", headers=manager).json()
    squawk = _plugin(view, SQUAWK)
    ok &= _step(
        [w["name"] for w in squawk["enabledWorkgroups"]] == [WORKGROUP],
        "enable state round-trips through GET /plugins",
    )

    # 5. Config set + get round-trip (the form's Save settings path).
    new_config = {"channel": "crew-north", "squelch": {"enabled": True, "threshold": -50}}
    r = httpx.put(
        f"{reg_url}/plugins/{SQUAWK}/config",
        json={"scope": "workgroup", "target": WORKGROUP, "config": new_config},
        headers=manager,
    )
    got = httpx.get(
        f"{reg_url}/plugins/{SQUAWK}/config",
        params={"scope": "workgroup", "target": WORKGROUP},
        headers=manager,
    ).json()
    ok &= _step(
        r.status_code == 200 and got == {"config": new_config},
        "config set + get round-trip",
    )

    # 6. A device reports SSH plugin health; the view shows it in the entry.
    httpx.post(
        f"{reg_url}/plugins/{SSH}/health",
        json={"deviceId": "smoke-front-desk", "status": "ok"},
        headers=manager,
    )
    view = httpx.get(f"{reg_url}/plugins", headers=manager).json()
    health = _plugin(view, SSH)["health"]
    ok &= _step(
        health[0]["deviceId"] == "smoke-front-desk" and health[0]["status"] == "ok",
        "reported SSH health shows in GET /plugins",
    )

    # 7. Disable; the next read reflects it (config kept server-side).
    r = httpx.post(
        f"{reg_url}/plugins/{SQUAWK}/disable",
        json={"scope": "workgroup", "target": WORKGROUP},
        headers=manager,
    )
    view = httpx.get(f"{reg_url}/plugins", headers=manager).json()
    ok &= _step(
        r.status_code == 200 and _plugin(view, SQUAWK)["enabledWorkgroups"] == [],
        "disable round-trips through GET /plugins",
    )

    # 8. The audit trail names the manager on every plugin action, newest first.
    entries = httpx.get(f"{reg_url}/audit", headers=manager).json()["entries"]
    actions = [e["action"] for e in entries]
    ok &= _step(
        actions == ["plugin-disable", "plugin-config", "plugin-enable"]
        and all(e["actor"] == "manager-eddie" for e in entries)
        and all(e["pluginId"] == SQUAWK for e in entries)
        and all(e["scope"] == "workgroup" for e in entries),
        "GET /audit lists enable/config/disable with the actor and plugin",
    )

    print("SMOKE PASS" if ok else "SMOKE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
