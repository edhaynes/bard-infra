"""Single configuration layer for Bard.

Precedence (lowest -> highest), per CLAUDE.md §1:

    defaults  <  OS env vars  <  .env file  <  config file (YAML)  <  CLI flags

Nothing else in the codebase reads ``os.environ`` directly; collaborators
receive a :class:`Config` instance via dependency injection (CLAUDE.md §2).
"""

from __future__ import annotations

import ipaddress
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - PyYAML is a declared dependency
    yaml = None  # type: ignore[assignment]

ENV_PREFIX = "BARDPRO_"

# Bug #58: HMAC-SHA256 (the JWT signing alg) needs a key of at least the hash
# output size — 32 bytes — or it is offline-brute-forceable (RFC 7518 §3.2;
# PyJWT raises InsecureKeyLengthWarning below this). Enforced in
# ``Config.require`` so both load_config and JwtVerifier.from_config fail fast.
MIN_JWT_SECRET_BYTES = 32

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid. Fail fast, fail loud."""


@dataclass(frozen=True)
class Config:
    """Immutable, validated configuration. Build it via :func:`load_config`."""

    # Service bind / discovery
    router_host: str = "127.0.0.1"
    router_port: int = 8443
    registry_host: str = "127.0.0.1"
    registry_port: int = 8081
    # Scheme the agent uses to self-register. Default TLS. Plain HTTP is an
    # explicit opt-in (``allow_insecure_http``) — the demo runs it over
    # Tailscale, where WireGuard already encrypts the hop.
    registry_scheme: str = "https"
    # Required opt-in for registry_scheme=http. Without it, load_config fails
    # fast (post-demo tightening: insecure transport must never be a silent
    # one-env-var change).
    allow_insecure_http: bool = False
    agent_host: str = "127.0.0.1"
    agent_port: int = 8444

    # TLS — paths only; key material never lives in config.
    tls_cert_path: str | None = None
    tls_key_path: str | None = None

    # Auth — secret is REQUIRED at runtime and is never hardcoded.
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "bardllm-pro"

    # Per-device identity (Sprint B2 / ADR-0010, pragmatic JWT-class). OPT-IN:
    # the fleet-wide shared JWT secret stays the default so v1.x deployments
    # keep working. When ``device_identity_enabled`` is true the Registry issues
    # per-device credentials through the enrollment lifecycle (join-token ->
    # pending -> active -> revoked) and verifies them with a PerDeviceVerifier
    # that resolves each device's key by deviceId from ``device_store_path``.
    # ``device_join_secret`` signs/verifies the short-lived join tokens (its own
    # HMAC key, distinct from ``jwt_secret``); it is REQUIRED when the feature is
    # on (validated in :func:`_validate`). This is NOT the v3 PQ/MLS fabric.
    device_identity_enabled: bool = False
    device_store_path: str = "./device-state.json"
    device_join_secret: str | None = None
    device_join_token_ttl_s: float = 900.0
    device_token_ttl_s: float = 3600.0
    # The per-device HMAC secret THIS headless AGENT received at approval (its
    # own credential). Set on the agent side only; the Registry never reads it.
    # Used by ``agent.register.mint_agent_token`` to sign with sub=agent_id.
    # NOTE: the Flutter CLIENT tier moved to device-generated Ed25519 keys with
    # self-signed EdDSA tokens (ADR-0016/S3); the headless-agent symmetric path
    # here is a separate, still-HMAC credential not yet migrated to asymmetric.
    device_secret: str | None = None

    # Channel invites (Sprint B3 / feature #67/#69): the "send a link, click,
    # you're in" flow. Rides on device identity — only wired when
    # ``device_identity_enabled`` is true. ``channel_invite_secret`` signs the
    # single-use invite tokens (its OWN HMAC key, distinct from both
    # ``jwt_secret`` and ``device_join_secret``); REQUIRED when device identity
    # is on, and held to the same RFC 7518 §3.2 minimum length. ``invite_base_url``
    # is the public link/QR landing the invite token is embedded into (the
    # client mobile UI redeems it); REQUIRED when device identity is on.
    channel_invite_secret: str | None = None
    channel_invite_ttl_s: float = 604800.0  # 7 days — long enough to text a crew
    invite_base_url: str | None = None

    # Management-action audit log (Sprint B6 / feature #64): append-only JSONL
    # of console actions (approve/revoke/rename/workgroup — who, what, which
    # device, when). Wired alongside device identity in registry/main.py; its
    # own file, parallel to (never merged into) the device/agent/channel state
    # files, same per-concern rule those stores follow.
    audit_log_path: str = "./audit-log.jsonl"

    # Plugin manage (Sprint B8 / feature #65): the catalog dir holds the
    # *.manifest.json files (frozen plugin-manifest.schema.json seam); the
    # state file persists enable/config/health per plugin — its own file,
    # same per-concern rule as the stores above. ``plugin_health_ttl_s`` is
    # the freshness window for reported plugin health (a report older than
    # this reads as "stale" — the agent heartbeat rule applied to plugins;
    # default matches agent_ttl_s). Wired alongside device identity in
    # registry/main.py; a missing/invalid catalog fails fast at startup.
    plugin_catalog_dir: str = "./examples/plugins"
    plugin_state_path: str = "./plugin-state.json"
    plugin_health_ttl_s: float = 45.0

    # Zero-knowledge seed escrow (ADR-0016 / Step S7, recovery): the JSON file
    # persisting handle -> {publicKey, wraps, createdAt, updatedAt}. The wraps
    # are opaque ciphertext the server can never decrypt; the file is treated
    # as sensitive and gitignored (recovery-state.json*). Its own file, parallel
    # to (never merged into) the device/channel/agent/plugin state files, same
    # per-concern rule those stores follow. Wired alongside device identity in
    # registry/main.py (the escrow POST is authed by the device's own token).
    # No secret to validate — the store holds only undecryptable ciphertext.
    recovery_store_path: str = "./recovery-state.json"

    # Agent / registry
    agent_id: str = "agent-local"
    model_dir: str = "./models"
    registry_state_path: str = "./registry-state.json"
    power_profile_path: str | None = None

    # Fleet node-facts cache (feature #91 / ADR-0018): the directory ansible's
    # jsonfile fact cache writes to — ONE JSON file per host (filename ==
    # inventory hostname). The control-plane projector (registry/node_facts.py)
    # reads it and serves GET /nodes. A missing dir is fail-soft (empty node
    # list), so no startup validation is required. Path-driven, never hardcoded
    # in the module (BARDPRO_FACTS_CACHE_DIR overrides the default).
    facts_cache_dir: str = "ansible/.facts_cache"

    # Boot-time self-registration (demo Phase 1): when true, the agent advertises
    # itself (address + capability profile) to the Registry on startup, so nodes
    # join the fleet on their own. ``advertised_address`` defaults to
    # ``agent_host:agent_port``; ``capabilities`` is comma-separated (e.g. "gpu,llm").
    self_register: bool = False
    advertised_address: str | None = None
    capabilities: str | None = None

    # Liveness (feature #54): the agent re-POSTs /register as a heartbeat every
    # ``heartbeat_interval_s``; the registry marks an agent stale (excluded from
    # /pool and /schedule, kept in /agents for observability) once
    # ``now - last_seen > agent_ttl_s``. TTL = 3x interval tolerates two missed
    # heartbeats before a node is considered gone.
    heartbeat_interval_s: float = 15.0
    agent_ttl_s: float = 45.0

    # Outbound broker link (feature #59 / ADR-0013): opt-in. When enabled the
    # agent holds a persistent outbound WebSocket to the Router's
    # /v1/agent-link and serves dispatched infer frames through it — only
    # outbound 443 needed, no inbound reachability. ``broker_url`` is the full
    # WS URL (e.g. wss://router.example:8443/v1/agent-link); wss:// required
    # unless ``allow_insecure_http`` is set. Reconnects use exponential
    # backoff from ``broker_backoff_initial_s`` capped at
    # ``broker_backoff_max_s``.
    broker_enabled: bool = False
    broker_url: str | None = None
    broker_backoff_initial_s: float = 1.0
    broker_backoff_max_s: float = 60.0

    # Peer name-resolution policy (opt-in). When true, a PEER address (the broker
    # URL host and the agent's advertised address) MUST be a resolvable logical
    # name, not a raw IP literal — enforced via the vendored name-resolution
    # validator (common/name_resolution.py, mirror of bard-infra). Loopback
    # (127.0.0.1, ::1, localhost) and the broker://<id> sentinel are exempt.
    # Default ON ⇒ fabric peers must be resolvable logical names; set
    # BARDPRO_ENFORCE_PEER_NAME_RESOLUTION=false to allow raw-IP peers.
    enforce_peer_name_resolution: bool = True

    # Inference engine (Sprint 1) — swappable backend (CLAUDE.md §1/§2).
    # ``echo`` keeps the demo/fakes path; ``llamacpp`` talks to a llama.cpp
    # OpenAI-compatible server co-located with the agent.
    inference_backend: str = "echo"  # echo | llamacpp | vllm
    llama_base_url: str = "http://127.0.0.1:8080/v1"
    llama_model: str = "local-gguf"
    llama_api_key: str | None = None
    # vLLM is OpenAI-compatible, so it reuses the same forwarder as llama.cpp,
    # just pointed at vLLM's server (default port 8000). Set by the vLLM router
    # plugin (examples/plugins/vllm-router.manifest.json).
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_model: str = "Qwen/Qwen3-0.6B"
    vllm_api_key: str | None = None
    inference_max_tokens: int = 512
    inference_temperature: float = 0.7

    # Ops
    log_level: str = "INFO"
    log_format: str = "json"  # json | text (feature #55 structured logs)
    request_timeout_s: float = 30.0

    def require(self, *keys: str) -> Config:
        """Fail fast if any named key is unset. Call once at startup."""
        missing = [k for k in keys if getattr(self, k) in (None, "")]
        if missing:
            raise ConfigError(
                "Missing required configuration: "
                + ", ".join(f"{ENV_PREFIX}{k.upper()}" for k in missing)
            )
        # Bug #58: presence is not enough for the JWT secret — a short HMAC key
        # is brute-forceable. Keyed to jwt_secret so ``require`` stays generic.
        if "jwt_secret" in keys and len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ConfigError(
                f"{ENV_PREFIX}JWT_SECRET is too short: HMAC-SHA256 requires at "
                f"least {MIN_JWT_SECRET_BYTES} bytes (RFC 7518 §3.2)."
            )
        return self


def _to_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


# Explicit string -> type coercions for values sourced from env / .env text.
_CASTS: dict[str, Callable[[str], Any]] = {
    "router_port": int,
    "registry_port": int,
    "agent_port": int,
    "request_timeout_s": float,
    "inference_max_tokens": int,
    "inference_temperature": float,
    "self_register": _to_bool,
    "heartbeat_interval_s": float,
    "agent_ttl_s": float,
    "allow_insecure_http": _to_bool,
    "broker_enabled": _to_bool,
    "broker_backoff_initial_s": float,
    "broker_backoff_max_s": float,
    "enforce_peer_name_resolution": _to_bool,
    "device_identity_enabled": _to_bool,
    "device_join_token_ttl_s": float,
    "device_token_ttl_s": float,
    "channel_invite_ttl_s": float,
    "plugin_health_ttl_s": float,
}

_FIELD_NAMES = {f.name for f in fields(Config)}


def _coerce(key: str, value: Any) -> Any:
    if isinstance(value, str) and key in _CASTS:
        try:
            return _CASTS[key](value)
        except ValueError as exc:
            raise ConfigError(f"Invalid value for {key!r}: {value!r}") from exc
    return value


def _from_env(environ: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_key, raw_val in environ.items():
        if not raw_key.startswith(ENV_PREFIX):
            continue
        name = raw_key[len(ENV_PREFIX) :].lower()
        if name in _FIELD_NAMES:
            out[name] = raw_val
    return out


def _from_dotenv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    out: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key.startswith(ENV_PREFIX):
            key = key[len(ENV_PREFIX) :]
        key = key.lower()
        if key in _FIELD_NAMES:
            out[key] = val.strip().strip('"').strip("'")
    return out


def _from_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    if yaml is None:
        raise ConfigError("PyYAML is required to read a YAML config file")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a mapping")
    return {k: v for k, v in data.items() if k in _FIELD_NAMES}


def _validate(config: Config) -> Config:
    """Fail fast on insecure or invalid settings (CLAUDE.md §1 — validate at startup).

    ``registry_scheme=http`` downgrades agent self-registration to cleartext, so
    it requires the explicit ``allow_insecure_http`` opt-in; even then it logs a
    WARNING so an insecure fleet is never silent.
    """
    if config.registry_scheme == "http":
        if not config.allow_insecure_http:
            raise ConfigError(
                "registry_scheme=http sends agent registration in cleartext. "
                f"Set {ENV_PREFIX}ALLOW_INSECURE_HTTP=true to opt in explicitly — "
                "only over an already-encrypted hop (e.g. Tailscale/WireGuard)."
            )
        logger.warning(
            "INSECURE TRANSPORT: registry_scheme=http — agent self-registration "
            "is not TLS-protected (explicit %sALLOW_INSECURE_HTTP opt-in). "
            "Acceptable only over an already-encrypted hop such as "
            "Tailscale/WireGuard.",
            ENV_PREFIX,
        )
    elif config.registry_scheme != "https":
        raise ConfigError(
            f"Invalid registry_scheme {config.registry_scheme!r}: must be 'https' "
            "or 'http' (http additionally requires "
            f"{ENV_PREFIX}ALLOW_INSECURE_HTTP=true)."
        )
    if config.broker_enabled:
        _validate_broker_url(config)
    if config.device_identity_enabled:
        _validate_device_identity(config)
    _validate_advertised_address(config)
    return config


# Loopback peers are always exempt from the name-resolution policy: localhost and
# the IPv4/IPv6 loopback literals are the local-dev/self default, not fabric peers.
_LOOPBACK_NAMES = frozenset({"localhost"})
_BROKER_SENTINEL_PREFIX = "broker://"


def _validate_peer_address(host: str, field_name: str, *, config: Config) -> None:
    """Enforce 'a PEER address is a resolvable logical name, not a raw IP'.

    No-op unless ``config.enforce_peer_name_resolution``. Exempts the empty/None
    skip case, ``localhost`` and any loopback IP literal, and the
    ``broker://<id>`` sentinel. Otherwise delegates to the vendored
    :func:`validate_endpoint`; ``RawIPError`` / ``NameResolutionError`` are
    ``ConfigError`` subclasses and propagate (fail-fast). The validator rejects
    ALL raw IPs (loopback included), so the loopback exemption MUST be returned
    before calling it.
    """
    if not config.enforce_peer_name_resolution:
        return
    if not host:
        return
    if host.startswith(_BROKER_SENTINEL_PREFIX):
        return
    if host in _LOOPBACK_NAMES:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass  # not an IP literal — fall through to name resolution
    # Lazy import INSIDE the function to avoid the circular import:
    # name_resolution imports ConfigError from this module.
    from common.name_resolution import SystemResolver, validate_endpoint

    validate_endpoint(host, SystemResolver())


def _validate_advertised_address(config: Config) -> None:
    """Flag-gated check of the agent's advertised PEER host (startup fail-fast).

    ``advertised_address`` has shape ``host:port`` (None ⇒ loopback default,
    skipped). The ``broker://<id>`` sentinel is passed through to the helper,
    which exempts it. IPv6 literals may be bracketed (``[::1]:8444``); strip the
    brackets before splitting so the loopback exemption sees the bare address.
    """
    advertised = config.advertised_address
    if not advertised:
        return
    if advertised.startswith(_BROKER_SENTINEL_PREFIX):
        host = advertised
        _validate_peer_address(host, "advertised_address", config=config)
        return
    # A schemed advertised address (e.g. ``http://gx10:8451``) is the demo/HTTP
    # form the agent registers with; strip a leading ``scheme://`` so the host
    # extraction below sees ``host[:port]``, not ``scheme://host``. ``//`` alone
    # (scheme-relative) is also tolerated.
    scheme_sep = advertised.find("://")
    if scheme_sep != -1:
        advertised = advertised[scheme_sep + 3 :]
    elif advertised.startswith("//"):
        advertised = advertised[2:]
    if advertised.startswith("["):  # bracketed IPv6, optionally [host]:port
        host = advertised[1:].split("]", 1)[0]
    else:
        host = advertised.rsplit(":", 1)[0] if ":" in advertised else advertised
    _validate_peer_address(host, "advertised_address", config=config)


def _validate_device_identity(config: Config) -> None:
    """Per-device identity opt-in (Sprint B2) needs a join-token signing secret,
    and it MUST meet the same HMAC minimum length as the fleet JWT secret (bug
    #58 / RFC 7518 §3.2) — a short join-token key is brute-forceable, which
    would let an attacker forge join tokens and enroll rogue devices."""
    if not config.device_join_secret:
        raise ConfigError(
            f"{ENV_PREFIX}DEVICE_IDENTITY_ENABLED=true requires "
            f"{ENV_PREFIX}DEVICE_JOIN_SECRET (the join-token signing key)."
        )
    if len(config.device_join_secret.encode()) < MIN_JWT_SECRET_BYTES:
        raise ConfigError(
            f"{ENV_PREFIX}DEVICE_JOIN_SECRET is too short: HMAC-SHA256 requires "
            f"at least {MIN_JWT_SECRET_BYTES} bytes (RFC 7518 §3.2)."
        )
    # Channel invites (Sprint B3) ride on device identity: an enabled fleet can
    # mint shareable channel invites, so the invite signing key and the link
    # base URL are required and the key meets the same HMAC minimum length (a
    # short invite key is brute-forceable, letting an attacker forge invites and
    # admit rogue devices into a channel with no approve gate).
    if not config.channel_invite_secret:
        raise ConfigError(
            f"{ENV_PREFIX}DEVICE_IDENTITY_ENABLED=true requires "
            f"{ENV_PREFIX}CHANNEL_INVITE_SECRET (the channel-invite signing key)."
        )
    if len(config.channel_invite_secret.encode()) < MIN_JWT_SECRET_BYTES:
        raise ConfigError(
            f"{ENV_PREFIX}CHANNEL_INVITE_SECRET is too short: HMAC-SHA256 "
            f"requires at least {MIN_JWT_SECRET_BYTES} bytes (RFC 7518 §3.2)."
        )
    if not config.invite_base_url:
        raise ConfigError(
            f"{ENV_PREFIX}DEVICE_IDENTITY_ENABLED=true requires "
            f"{ENV_PREFIX}INVITE_BASE_URL (the link/QR landing the invite "
            "token is embedded into for client redemption)."
        )


def _validate_broker_url(config: Config) -> None:
    """Broker opt-in (feature #59) needs a URL, and the same wss-by-default
    rigor as ``registry_scheme``: plain ws:// is cleartext, so it requires the
    explicit ``allow_insecure_http`` opt-in and still logs a WARNING."""
    if not config.broker_url:
        raise ConfigError(
            f"{ENV_PREFIX}BROKER_ENABLED=true requires {ENV_PREFIX}BROKER_URL "
            "(the Router's wss:// /v1/agent-link endpoint)."
        )
    if config.broker_url.startswith("ws://"):
        if not config.allow_insecure_http:
            raise ConfigError(
                "broker_url uses ws:// — the agent link would run in cleartext. "
                f"Set {ENV_PREFIX}ALLOW_INSECURE_HTTP=true to opt in explicitly — "
                "only over an already-encrypted hop (e.g. Tailscale/WireGuard)."
            )
        logger.warning(
            "INSECURE TRANSPORT: broker_url is ws:// — the outbound agent link "
            "is not TLS-protected (explicit %sALLOW_INSECURE_HTTP opt-in).",
            ENV_PREFIX,
        )
    elif not config.broker_url.startswith("wss://"):
        raise ConfigError(
            f"Invalid broker_url {config.broker_url!r}: must be wss:// "
            f"(or ws:// with {ENV_PREFIX}ALLOW_INSECURE_HTTP=true)."
        )
    # Peer name-resolution policy (opt-in, no-op when off): the broker host is a
    # fabric PEER. Run AFTER the scheme checks so current errors fire first.
    from urllib.parse import urlparse

    host = urlparse(config.broker_url).hostname
    _validate_peer_address(host or "", "broker_url host", config=config)


def load_config(
    *,
    config_file: str | os.PathLike[str] | None = None,
    dotenv_path: str | os.PathLike[str] | None = ".env",
    cli_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Merge all sources in increasing precedence and build a :class:`Config`.

    ``defaults < env vars < .env < config file < CLI overrides``
    """
    environ = os.environ if environ is None else environ
    merged: dict[str, Any] = {}
    merged.update(_from_env(environ))
    if dotenv_path is not None:
        merged.update(_from_dotenv(Path(dotenv_path)))
    if config_file is not None:
        merged.update(_from_yaml(Path(config_file)))
    if cli_overrides:
        merged.update({k: v for k, v in cli_overrides.items() if k in _FIELD_NAMES})

    coerced = {k: _coerce(k, v) for k, v in merged.items()}
    try:
        config = Config(**coerced)
    except TypeError as exc:  # an unknown field slipped through
        raise ConfigError(str(exc)) from exc
    return _validate(config)
