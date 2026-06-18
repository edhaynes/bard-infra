"""Boot-time self-registration (demo Phase 1) + liveness heartbeat (feature #54).

The agent advertises itself — address + capability profile — to the Registry on
startup, so heterogeneous nodes appear in the fleet on their own, then keeps
re-POSTing the same ``/register`` body on an interval so the Registry's
``lastSeen`` stays fresh (no new endpoint; the contract is unchanged). Pure
builders plus injectable HTTP client / sleep keep this unit-testable with no
network and no real waiting.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import jwt

from common.config import Config, ConfigError

logger = logging.getLogger(__name__)

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - PyYAML is a declared dependency
    yaml = None  # type: ignore[assignment]


def load_power_profile(path: str | None) -> dict[str, Any] | None:
    """Load the agent's power profile from a YAML file, or None when unset."""
    if not path:
        return None
    if yaml is None:  # pragma: no cover - PyYAML is a declared dependency
        raise RuntimeError("PyYAML is required to read a power-profile file")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"power profile {path} must be a mapping")
    return data


def _parse_capabilities(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


def build_registration(config: Config) -> dict[str, Any]:
    """Assemble the AgentRegistration body (registry.openapi.yaml) from config."""
    address = config.advertised_address or f"{config.agent_host}:{config.agent_port}"
    body: dict[str, Any] = {"agentId": config.agent_id, "address": address}
    caps = _parse_capabilities(config.capabilities)
    if caps:
        body["capabilities"] = caps
    profile = load_power_profile(config.power_profile_path)
    if profile is not None:
        body["powerProfile"] = profile
    return body


def build_link_registration(config: Config) -> dict[str, Any]:
    """Assemble the register/heartbeat frame body for broker mode (slice 2).

    Mirrors :func:`build_registration` but for the link path: it omits
    ``agentId`` (the link's hello already established identity — the Router
    binds the registration to it, never to a frame-supplied id; bug #54), and
    it omits ``address`` unless one is explicitly configured (the Router
    synthesizes the ``broker://<agentId>`` sentinel otherwise). ``capabilities``
    / ``powerProfile`` are advertised the same as the HTTP path.
    """
    body: dict[str, Any] = {}
    if config.advertised_address:
        body["advertisedAddress"] = config.advertised_address
    caps = _parse_capabilities(config.capabilities)
    if caps:
        body["capabilities"] = caps
    profile = load_power_profile(config.power_profile_path)
    if profile is not None:
        body["powerProfile"] = profile
    return body


def mint_agent_token(config: Config, *, now: _dt.datetime | None = None) -> str:
    """Mint a short-lived JWT the Registry accepts.

    Per-device path (Sprint B2 / ADR-0010): when ``device_identity_enabled`` is
    set, the agent signs with ITS OWN per-device secret (``device_secret``) and
    sub=agent_id (the deviceId), so the Registry's PerDeviceVerifier resolves the
    matching key. Otherwise it falls back to the fleet-wide shared ``jwt_secret``
    (the v1.x default), keeping existing deployments working. Both carry the same
    claim shape (sub/iss/iat/exp) — the verifier seam is the only thing that
    differs (CLAUDE.md §6 "use X locally" => configurable, not hardcoded).
    """
    issued = now or _dt.datetime.now(_dt.UTC)
    if config.device_identity_enabled:
        secret = config.device_secret
        ttl = config.device_token_ttl_s
    else:
        secret = config.jwt_secret
        ttl = 3600.0
    return jwt.encode(
        {
            "sub": config.agent_id,
            "iss": config.jwt_issuer,
            "iat": issued,
            "exp": issued + _dt.timedelta(seconds=ttl),
        },
        secret,
        algorithm=config.jwt_algorithm,
    )


def self_register(
    config: Config,
    *,
    client: httpx.Client | None = None,
    verify: Any = True,
) -> dict[str, Any] | None:
    """POST the agent's registration to the Registry.

    No-op (returns None) when self-registration is disabled. Raises on transport
    or HTTP error so the caller decides whether a missing registration is fatal.
    """
    if not config.self_register:
        return None
    config.require("device_secret" if config.device_identity_enabled else "jwt_secret")
    body = build_registration(config)
    token = mint_agent_token(config)
    url = f"{config.registry_scheme}://{config.registry_host}:{config.registry_port}/register"
    owns_client = client is None
    client = client or httpx.Client(verify=verify, timeout=config.request_timeout_s)
    try:
        resp = client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_client:
            client.close()


async def heartbeat_loop(
    config: Config,
    *,
    client: httpx.Client | None = None,
    verify: Any = True,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    """Re-POST ``/register`` every ``heartbeat_interval_s`` so the Registry's
    ``lastSeen`` stays fresh (feature #54).

    Runs until cancelled (the agent app cancels it on shutdown). Failures are
    logged and non-fatal — the loop keeps retrying on the same interval so a
    briefly-down Registry doesn't kill the agent. ``sleep`` is injectable so
    tests drive the loop without real waiting.
    """
    do_sleep = sleep or asyncio.sleep
    while True:
        await do_sleep(config.heartbeat_interval_s)
        try:
            # self_register is sync httpx; run it off the event loop so a slow
            # Registry never blocks the agent's request handling.
            await asyncio.to_thread(self_register, config, client=client, verify=verify)
        except (httpx.HTTPError, ConfigError) as exc:
            logger.warning("agent heartbeat re-registration failed: %s", exc)
