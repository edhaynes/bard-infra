"""Full control-plane Registry entrypoint WITH CORS, for the browser console.

Same CORS surface as ``scripts.registry_cors`` (a Vite console on
``http://localhost:5173`` / the ``127.0.0.1`` variant reads ``/fleet`` and the
management routes cross-origin), but unlike that lightweight fleet-only
entrypoint this one also wires the **device-identity control plane**: the
``DeviceStore`` (enrollment + workgroups), ``ChannelStore`` (invites),
``AuditLog`` (console-action ledger), and ``PluginStore`` (plugin catalog +
enable/config/health). It is ``registry.main`` plus ``cors_origins`` — the
console needs all three of ``/fleet``, ``/plugins`` and ``/audit`` live and
cross-origin.

Run with::

    uv run uvicorn console_registry:app \
        --app-dir scripts --host 0.0.0.0 --port 8081

Configuration (all via the single ``common.config`` layer — no direct
``os.environ`` reads except the CORS-origins list, which mirrors
``registry_cors``):

* ``BARDPRO_CONSOLE_ORIGINS`` (comma-separated) — allowed browser origins;
  defaults to the Vite dev server (``localhost``/``127.0.0.1`` :5173).
* ``BARDPRO_DEVICE_IDENTITY_ENABLED=true`` — turns the control plane on. When
  set, ``BARDPRO_DEVICE_JOIN_SECRET``, ``BARDPRO_CHANNEL_INVITE_SECRET`` and
  ``BARDPRO_INVITE_BASE_URL`` become required (config validation fails fast
  otherwise — see ``common.config._validate_device_identity``).
* ``BARDPRO_PLUGIN_CATALOG_DIR`` — directory of ``*.manifest.json`` plugin
  manifests (default ``./examples/plugins``); an invalid/missing dir crashes
  loudly at startup.
* ``BARDPRO_DEVICE_STORE_PATH`` / ``BARDPRO_PLUGIN_STATE_PATH`` /
  ``BARDPRO_AUDIT_LOG_PATH`` / ``BARDPRO_REGISTRY_STATE_PATH`` — persistence
  paths for each store (each its own file, per-concern). The channel store
  derives its file as ``<device_store_path>.channels``.

When device identity is *off*, this degrades to exactly the ``registry_cors``
surface (fleet view only, no device/plugin routes) — same swappable-backend
shape, one entrypoint.

Portable: this file lives in ``<repo>/scripts/``; the repo root is derived from
``__file__`` so the module imports regardless of cwd / ``--app-dir``. No
hardcoded home directory or absolute path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo importable regardless of cwd / --app-dir: this file lives in
# ``<repo>/scripts/``, so the repo root is its parent's parent. Portable — no
# hardcoded home path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.auth import JwtVerifier  # noqa: E402
from common.config import load_config  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from registry.app import create_app  # noqa: E402
from registry.audit_log import AuditLog  # noqa: E402
from registry.channel_store import ChannelStore  # noqa: E402
from registry.device_store import DeviceStore  # noqa: E402
from registry.plugin_store import PluginStore  # noqa: E402
from registry.store import RegistryStore  # noqa: E402

_config = load_config()
configure_logging(_config)

_origins = os.environ.get(
    "BARDPRO_CONSOLE_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# Control-plane stores — built exactly as registry/main.py does, gated on the
# device-identity opt-in. When the feature is off, all four stay None and the
# app exposes only the fleet-only surface (registry_cors parity).
_device_store = (
    DeviceStore(
        _config.device_store_path,
        join_token_secret=_config.device_join_secret,
        issuer=_config.jwt_issuer,
    )
    if _config.device_identity_enabled
    else None
)
_channel_store = (
    ChannelStore(
        _device_store,
        _config.device_store_path + ".channels",
        invite_secret=_config.channel_invite_secret,
        issuer=_config.jwt_issuer,
        invite_base_url=_config.invite_base_url,
    )
    if _device_store is not None
    else None
)
_audit_log = AuditLog(_config.audit_log_path) if _device_store is not None else None
_plugin_store = (
    PluginStore(
        _config.plugin_catalog_dir,
        _config.plugin_state_path,
        health_ttl_s=_config.plugin_health_ttl_s,
    )
    if _device_store is not None
    else None
)

app = create_app(
    RegistryStore(_config.registry_state_path, ttl_s=_config.agent_ttl_s),
    JwtVerifier.from_config(_config),
    cors_origins=[o.strip() for o in _origins if o.strip()],
    device_store=_device_store,
    channel_store=_channel_store,
    default_invite_ttl_s=_config.channel_invite_ttl_s,
    audit_log=_audit_log,
    plugin_store=_plugin_store,
)
