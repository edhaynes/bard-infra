"""Router entrypoint. ``uvicorn router.main:app``.

Requires BARDPRO_JWT_SECRET at startup (fails fast otherwise).
"""

from __future__ import annotations

from common.auth import FleetTokenMinter, JwtVerifier, TokenVerifier
from common.config import load_config
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from common.logging import configure_logging
from common.metrics import AppMetrics, BrokerMetrics
from registry.device_store import DeviceStore
from router.app import create_app
from router.broker import BrokerLinkManager
from router.clients import HttpAgentClient, HttpRegistryClient

_config = load_config()
configure_logging(_config)
_verify: bool | str = _config.tls_cert_path or True
_registry = HttpRegistryClient.from_config(
    _config,
    verify=_verify,
    timeout=_config.request_timeout_s,
)
_agent = HttpAgentClient(verify=_verify, timeout=_config.request_timeout_s)
_metrics = AppMetrics("router")
# /v1/agent-link is always served (feature #59 / ADR-0013); whether any agent
# uses it is the agent-side opt-in (BARDPRO_BROKER_ENABLED).
_broker = BrokerLinkManager(timeout_s=_config.request_timeout_s, metrics=BrokerMetrics(_metrics))
# Relay auth on per-device identity (Sprint B4 / bug #56): when device identity
# is enabled, the data path (/v1/message + the broker link hello) accepts EITHER
# the fleet JWT (legacy agents, opt-in coexistence) OR a per-device token
# verified against the device store — so an unknown, pending, or revoked device
# cannot relay. The store is read-only here (the Registry writes it) and
# reload_on_read makes a Registry-side revoke take effect on the next request.
# Bug #63: the Router authenticates its OWN internal registry lookups with a
# short-lived fleet service token (signed from BARDPRO_JWT_SECRET) instead of
# forwarding the caller's per-device token, which the fleet-only Registry would
# reject. Built unconditionally — the fleet secret is always present (the
# verifier below requires it) and the minter is harmless on the legacy
# fleet-token path (the token it mints is itself a valid fleet token).
_service_tokens = FleetTokenMinter.from_config(_config)
_verifier: TokenVerifier = JwtVerifier.from_config(_config)
if _config.device_identity_enabled:
    _verifier = FleetOrDeviceVerifier(
        _verifier,
        PerDeviceVerifier(
            DeviceStore(
                _config.device_store_path,
                join_token_secret=_config.device_join_secret,
                issuer=_config.jwt_issuer,
                reload_on_read=True,
            ),
            issuer=_config.jwt_issuer,
        ),
    )
app = create_app(
    _registry,
    _agent,
    _verifier,
    metrics=_metrics,
    broker=_broker,
    service_tokens=_service_tokens,
)
