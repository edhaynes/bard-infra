"""Registry entrypoint. ``uvicorn registry.main:app``.

Requires BARDPRO_JWT_SECRET at startup (fails fast otherwise).
"""

from __future__ import annotations

from common.auth import JwtVerifier
from common.config import load_config
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from common.logging import configure_logging
from registry.app import create_app
from registry.audit_log import AuditLog
from registry.channel_store import ChannelStore
from registry.device_store import DeviceStore
from registry.plugin_store import PluginStore
from registry.store import RegistryStore

_config = load_config()
configure_logging(_config)

# Per-device identity (Sprint B2 / ADR-0010) is opt-in: when enabled, build the
# DeviceStore that backs the enrollment endpoints; config validation (§0.11)
# guarantees device_join_secret is present and long enough. Management endpoints
# stay behind the fleet JwtVerifier (the manager authenticates with the admin
# JWT); per-device credentials govern the data-plane traffic at the Router.
_device_store = (
    DeviceStore(
        _config.device_store_path,
        join_token_secret=_config.device_join_secret,
        issuer=_config.jwt_issuer,
    )
    if _config.device_identity_enabled
    else None
)
# Channel invites (Sprint B3 / feature #67/#69) ride on device identity: built
# only when it is enabled, and only then alongside the DeviceStore it admits
# devices through. Config validation guarantees the invite secret + base URL.
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
# Management-action audit (Sprint B6 / feature #64) rides on device identity
# like the stores above: console actions only exist when devices do.
_audit_log = AuditLog(_config.audit_log_path) if _device_store is not None else None
# Plugin manage (Sprint B8 / feature #65) rides on device identity too — the
# console's plugin pane targets enrolled devices/workgroups. An invalid or
# missing catalog dir crashes loudly here at startup (§0.11), never limps.
_plugin_store = (
    PluginStore(
        _config.plugin_catalog_dir,
        _config.plugin_state_path,
        health_ttl_s=_config.plugin_health_ttl_s,
    )
    if _device_store is not None
    else None
)
# Owner actions (ADR-0016 / Step S5) accept a per-device token OR the fleet/admin
# JWT: when device identity is on, the Registry verifies with a
# FleetOrDeviceVerifier so a self-registered device's own token can create and
# manage the box it owns (retiring the baked fleet token for owner actions, #67).
# Fleet-only deployments (device identity off) keep the plain JwtVerifier.
_fleet_verifier = JwtVerifier.from_config(_config)
_verifier = (
    FleetOrDeviceVerifier(
        _fleet_verifier,
        PerDeviceVerifier(_device_store, issuer=_config.jwt_issuer),
    )
    if _device_store is not None
    else _fleet_verifier
)
app = create_app(
    RegistryStore(_config.registry_state_path, ttl_s=_config.agent_ttl_s),
    _verifier,
    device_store=_device_store,
    channel_store=_channel_store,
    default_invite_ttl_s=_config.channel_invite_ttl_s,
    audit_log=_audit_log,
    plugin_store=_plugin_store,
)
