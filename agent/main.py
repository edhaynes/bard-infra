"""Agent entrypoint. ``uvicorn agent.main:app``.

Requires BARDPRO_JWT_SECRET at startup (fails fast otherwise).
"""

from __future__ import annotations

import functools
import logging

import httpx

from agent import broker, register
from agent.app import create_app
from agent.engine import make_engine
from common.auth import JwtVerifier
from common.config import ConfigError, load_config
from common.logging import configure_logging

_config = load_config()
configure_logging(_config)
_verify = _config.tls_cert_path or True

# Boot-time self-registration (demo Phase 1) — advertise this node (address +
# capability profile) to the Registry so it joins the fleet on its own. Non-fatal:
# log and continue so the agent still serves if the Registry is briefly down.
# While self-registration is on, a background heartbeat (feature #54) re-POSTs
# /register every heartbeat_interval_s so the Registry's lastSeen stays fresh.
#
# Single front door (slice 2 / ADR-0013): in broker mode the agent registers and
# heartbeats OVER THE LINK (the Router relays to the now-private Registry), so the
# direct HTTP /register + heartbeat loop is suppressed — exactly one registration
# path, chosen by config. Direct mode (broker off) is completely unchanged.
_heartbeat = None
if _config.self_register and not _config.broker_enabled:
    try:
        register.self_register(_config, verify=_verify)
    except (httpx.HTTPError, ConfigError) as exc:
        logging.getLogger(__name__).warning("agent self-registration failed: %s", exc)
    _heartbeat = functools.partial(register.heartbeat_loop, _config, verify=_verify)

_engine = make_engine(_config)
_verifier = JwtVerifier.from_config(_config)

# Outbound broker link (feature #59 / ADR-0013) — opt-in: hold a persistent
# WS to the Router and serve dispatched infer frames through the SAME engine
# as the HTTP path. In broker mode the link also carries registration +
# heartbeat (slice 2), replacing the direct path suppressed above.
_broker = None
if _config.broker_enabled:
    _broker = functools.partial(broker.broker_loop, _config, _engine, _verifier)

app = create_app(
    _engine,
    _verifier,
    heartbeat=_heartbeat,
    broker=_broker,
    backend_name=_config.inference_backend,
)
