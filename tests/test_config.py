"""Unit tests for the configuration layer (common/config.py).

Covers every source and precedence rule in ``load_config`` plus the validation
branches: env, .env file, YAML file, CLI overrides, type coercion (incl. bad
casts), ``require``, and unknown-field handling. No real environment is read —
``environ`` is injected (CLAUDE.md §1/§2).
"""

from __future__ import annotations

import pytest

from common.config import (
    ENV_PREFIX,
    Config,
    ConfigError,
    _coerce,
    _from_dotenv,
    _from_env,
    _from_yaml,
    load_config,
)


def test_defaults_when_no_sources():
    cfg = load_config(dotenv_path=None, environ={})
    assert cfg.router_port == 8443
    assert cfg.inference_backend == "echo"
    assert cfg.jwt_secret is None


def test_from_env_filters_prefix_and_unknown_keys():
    env = {
        f"{ENV_PREFIX}ROUTER_PORT": "9000",
        f"{ENV_PREFIX}UNKNOWN_THING": "x",  # not a Config field -> dropped
        "PATH": "/usr/bin",  # no prefix -> dropped
    }
    out = _from_env(env)
    assert out == {"router_port": "9000"}


def test_env_value_is_coerced_to_int():
    cfg = load_config(dotenv_path=None, environ={f"{ENV_PREFIX}ROUTER_PORT": "9001"})
    assert cfg.router_port == 9001 and isinstance(cfg.router_port, int)


def test_coerce_bad_value_raises_config_error():
    with pytest.raises(ConfigError) as exc:
        _coerce("router_port", "not-an-int")
    assert "router_port" in str(exc.value)


def test_coerce_non_cast_field_passthrough():
    assert _coerce("router_host", "1.2.3.4") == "1.2.3.4"


def test_coerce_non_string_value_passthrough():
    # Already-typed values (e.g. from YAML) skip the string cast path.
    assert _coerce("router_port", 8443) == 8443


def test_dotenv_overrides_env(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "# a comment",
                "",  # blank line
                "NOEQUALS",  # no '=' -> skipped
                f'{ENV_PREFIX}ROUTER_HOST="10.0.0.9"',  # quoted value -> stripped
                f"{ENV_PREFIX}UNKNOWN=ignored",  # unknown field -> dropped
                "router_port=7000",  # bare (no prefix) field name also accepted
            ]
        ),
        encoding="utf-8",
    )
    cfg = load_config(
        dotenv_path=dotenv,
        environ={f"{ENV_PREFIX}ROUTER_HOST": "1.1.1.1", f"{ENV_PREFIX}ROUTER_PORT": "1"},
    )
    assert cfg.router_host == "10.0.0.9"  # .env beat env
    assert cfg.router_port == 7000


def test_dotenv_missing_file_returns_empty(tmp_path):
    assert _from_dotenv(tmp_path / "nope.env") == {}


def test_yaml_config_overrides_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{ENV_PREFIX}LOG_LEVEL=DEBUG\n", encoding="utf-8")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "log_level: WARNING\nrequest_timeout_s: 12.5\nbogus_key: dropped\n", encoding="utf-8"
    )
    cfg = load_config(config_file=cfg_file, dotenv_path=dotenv, environ={})
    assert cfg.log_level == "WARNING"
    assert cfg.request_timeout_s == 12.5


def test_yaml_missing_file_returns_empty(tmp_path):
    assert _from_yaml(tmp_path / "nope.yaml") == {}


def test_yaml_non_mapping_raises(tmp_path):
    cfg_file = tmp_path / "list.yaml"
    cfg_file.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        _from_yaml(cfg_file)
    assert "mapping" in str(exc.value)


def test_yaml_empty_file_is_empty_dict(tmp_path):
    cfg_file = tmp_path / "empty.yaml"
    cfg_file.write_text("", encoding="utf-8")
    assert _from_yaml(cfg_file) == {}


def test_cli_overrides_win_and_filter_unknown(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("router_host: 2.2.2.2\n", encoding="utf-8")
    cfg = load_config(
        config_file=cfg_file,
        dotenv_path=None,
        environ={},
        cli_overrides={"router_host": "9.9.9.9", "not_a_field": "x"},
    )
    assert cfg.router_host == "9.9.9.9"


def test_require_raises_when_missing():
    cfg = Config()
    with pytest.raises(ConfigError) as exc:
        cfg.require("jwt_secret")
    assert f"{ENV_PREFIX}JWT_SECRET" in str(exc.value)


def test_require_returns_self_when_present():
    # >=32-byte secret clears both the presence and the #58 length check.
    cfg = Config(jwt_secret="a-sufficiently-long-jwt-secret-0123456789")  # gitleaks:allow
    assert cfg.require("jwt_secret") is cfg


def test_require_treats_empty_string_as_missing():
    with pytest.raises(ConfigError):
        Config(jwt_secret="").require("jwt_secret")


def test_require_rejects_short_jwt_secret():
    # Bug #58: a present-but-too-short HMAC key is brute-forceable; require()
    # must reject it and name the env var + the 32-byte minimum.
    short = "s" * 31  # one byte under the floor, non-empty
    with pytest.raises(ConfigError) as exc:
        Config(jwt_secret=short).require("jwt_secret")
    msg = str(exc.value)
    assert f"{ENV_PREFIX}JWT_SECRET" in msg
    assert "32" in msg


def test_require_accepts_exactly_min_length_jwt_secret():
    # Boundary: exactly 32 bytes is allowed (the floor is inclusive).
    cfg = Config(jwt_secret="x" * 32)
    assert cfg.require("jwt_secret") is cfg


def test_http_scheme_without_opt_in_fails_fast():
    # Post-demo tightening: plain HTTP must never be a silent one-env-var change.
    with pytest.raises(ConfigError) as exc:
        load_config(dotenv_path=None, environ={f"{ENV_PREFIX}REGISTRY_SCHEME": "http"})
    assert f"{ENV_PREFIX}ALLOW_INSECURE_HTTP" in str(exc.value)


def test_http_scheme_with_opt_in_loads_and_warns(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="common.config"):
        cfg = load_config(
            dotenv_path=None,
            environ={
                f"{ENV_PREFIX}REGISTRY_SCHEME": "http",
                f"{ENV_PREFIX}ALLOW_INSECURE_HTTP": "true",
            },
        )
    assert cfg.registry_scheme == "http"
    assert cfg.allow_insecure_http is True
    assert any("INSECURE TRANSPORT" in r.getMessage() for r in caplog.records)


def test_https_scheme_loads_silently(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="common.config"):
        cfg = load_config(dotenv_path=None, environ={})
    assert cfg.registry_scheme == "https"
    assert not any("INSECURE" in r.getMessage() for r in caplog.records)


def test_unknown_scheme_raises():
    with pytest.raises(ConfigError, match="Invalid registry_scheme"):
        load_config(dotenv_path=None, environ={f"{ENV_PREFIX}REGISTRY_SCHEME": "ftp"})


def test_yaml_without_pyyaml_raises(tmp_path, monkeypatch):
    import common.config as config_mod

    # Simulate PyYAML being unavailable (the import guard's None branch).
    monkeypatch.setattr(config_mod, "yaml", None)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("router_host: 1.2.3.4\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="PyYAML is required"):
        _from_yaml(cfg_file)


def test_load_config_unknown_field_raises_config_error(monkeypatch):
    import common.config as config_mod

    # Force an unknown field past the per-source filters so Config(**coerced)
    # raises TypeError, which load_config wraps as ConfigError.
    monkeypatch.setattr(config_mod, "_from_env", lambda environ: {"bogus_field": "x"})
    with pytest.raises(ConfigError):
        load_config(dotenv_path=None, environ={})


# --- Sprint B2 per-device identity opt-in validation (fail-fast, §0.11) ------


def test_device_identity_disabled_by_default():
    cfg = load_config(dotenv_path=None, environ={})
    assert cfg.device_identity_enabled is False
    assert cfg.device_join_secret is None


def test_device_identity_enabled_requires_join_secret():
    with pytest.raises(ConfigError, match="DEVICE_JOIN_SECRET"):
        load_config(
            dotenv_path=None,
            environ={f"{ENV_PREFIX}DEVICE_IDENTITY_ENABLED": "true"},
        )


def test_device_identity_join_secret_too_short_rejected():
    with pytest.raises(ConfigError, match="too short"):
        load_config(
            dotenv_path=None,
            environ={
                f"{ENV_PREFIX}DEVICE_IDENTITY_ENABLED": "true",
                f"{ENV_PREFIX}DEVICE_JOIN_SECRET": "short",
            },
        )


# Channel invites (Sprint B3) ride on device identity, so every "device
# identity enabled" config must also supply the invite signing key + base URL.
_INVITE_ENV = {
    f"{ENV_PREFIX}CHANNEL_INVITE_SECRET": "y" * 32,
    f"{ENV_PREFIX}INVITE_BASE_URL": "https://join.bardllm.dev/i",
}


def _device_identity_env(**extra: str) -> dict[str, str]:
    return {
        f"{ENV_PREFIX}DEVICE_IDENTITY_ENABLED": "true",
        f"{ENV_PREFIX}DEVICE_JOIN_SECRET": "x" * 32,
        **_INVITE_ENV,
        **extra,
    }


def test_device_identity_enabled_loads_with_valid_secrets():
    cfg = load_config(dotenv_path=None, environ=_device_identity_env())
    assert cfg.device_identity_enabled is True
    assert cfg.device_store_path == "./device-state.json"
    assert cfg.channel_invite_secret == "y" * 32
    assert cfg.invite_base_url == "https://join.bardllm.dev/i"
    assert cfg.channel_invite_ttl_s == 604800.0


def test_device_identity_requires_channel_invite_secret():
    env = _device_identity_env()
    del env[f"{ENV_PREFIX}CHANNEL_INVITE_SECRET"]
    with pytest.raises(ConfigError, match="CHANNEL_INVITE_SECRET"):
        load_config(dotenv_path=None, environ=env)


def test_device_identity_channel_invite_secret_too_short_rejected():
    with pytest.raises(ConfigError, match="too short"):
        load_config(
            dotenv_path=None,
            environ=_device_identity_env(**{f"{ENV_PREFIX}CHANNEL_INVITE_SECRET": "short"}),
        )


def test_device_identity_requires_invite_base_url():
    env = _device_identity_env()
    del env[f"{ENV_PREFIX}INVITE_BASE_URL"]
    with pytest.raises(ConfigError, match="INVITE_BASE_URL"):
        load_config(dotenv_path=None, environ=env)


def test_channel_invite_ttl_override_coerced():
    cfg = load_config(
        dotenv_path=None,
        environ=_device_identity_env(**{f"{ENV_PREFIX}CHANNEL_INVITE_TTL_S": "120"}),
    )
    assert cfg.channel_invite_ttl_s == 120.0


# --- Peer name-resolution policy (opt-in, default OFF) -----------------------
#
# Hermetic: socket.getaddrinfo is monkeypatched so named peers "resolve" and
# unknown names raise socket.gaierror. NO real network is touched. The flag is
# default-OFF, so the first test proves raw-IP peers still load unchanged.


@pytest.fixture
def fake_dns(monkeypatch):
    """Stub the OS resolver: ``known.peer`` resolves; everything else fails."""
    import socket

    resolvable = {"known.peer", "gx10"}

    def fake_getaddrinfo(host, *args, **kwargs):
        if host in resolvable:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.1.2.3", 0))]
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return resolvable


def _broker_env(host_url: str, **extra: str) -> dict[str, str]:
    return {
        f"{ENV_PREFIX}BROKER_ENABLED": "true",
        f"{ENV_PREFIX}BROKER_URL": host_url,
        **extra,
    }


def test_enforce_flag_on_by_default():
    # Flag flipped ON by default: a freshly loaded Config with nothing set
    # enforces the peer name-resolution policy.
    cfg = load_config(dotenv_path=None, environ={})
    assert cfg.enforce_peer_name_resolution is True


def test_enforce_flag_bool_coercion_true_false():
    on = load_config(
        dotenv_path=None,
        environ={f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true"},
    )
    off = load_config(
        dotenv_path=None,
        environ={f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "false"},
    )
    assert on.enforce_peer_name_resolution is True
    assert off.enforce_peer_name_resolution is False


def test_flag_off_raw_ip_broker_host_loads(fake_dns):
    # Flag explicitly OFF: a raw-IP broker peer loads fine (the opt-out path).
    cfg = load_config(
        dotenv_path=None,
        environ=_broker_env(
            "wss://10.0.0.5:8443/x",
            **{f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "false"},
        ),
    )
    assert cfg.broker_url == "wss://10.0.0.5:8443/x"


def test_flag_off_raw_ip_advertised_loads(fake_dns):
    # Flag explicitly OFF: a raw-IP advertised peer loads fine (the opt-out path).
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "false",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "10.0.0.5:8444",
        },
    )
    assert cfg.advertised_address == "10.0.0.5:8444"


def test_default_on_raw_ip_broker_host_rejected(fake_dns):
    # The default (nothing set for the flag) actually enforces: a raw-IP broker
    # peer is rejected with RawIPError (a ConfigError subclass). No explicit
    # ENFORCE_PEER_NAME_RESOLUTION env var — proving the default does the work.
    from common.name_resolution import RawIPError

    with pytest.raises((ConfigError, RawIPError)):
        load_config(dotenv_path=None, environ=_broker_env("wss://10.0.0.5:8443/x"))


def test_flag_on_resolvable_broker_host_loads(fake_dns):
    cfg = load_config(
        dotenv_path=None,
        environ=_broker_env(
            "wss://known.peer:8443/v1/agent-link",
            **{f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true"},
        ),
    )
    assert cfg.broker_url == "wss://known.peer:8443/v1/agent-link"


def test_flag_on_resolvable_advertised_loads(fake_dns):
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "gx10:8444",
        },
    )
    assert cfg.advertised_address == "gx10:8444"


def test_flag_on_raw_ip_advertised_raises_raw_ip_error(fake_dns):
    from common.name_resolution import RawIPError

    with pytest.raises(RawIPError):
        load_config(
            dotenv_path=None,
            environ={
                f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
                f"{ENV_PREFIX}ADVERTISED_ADDRESS": "10.0.0.5:8444",
            },
        )


def test_flag_on_raw_ip_broker_host_raises_raw_ip_error(fake_dns):
    from common.name_resolution import RawIPError

    with pytest.raises(RawIPError):
        load_config(
            dotenv_path=None,
            environ=_broker_env(
                "wss://10.0.0.5:8443/x",
                **{f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true"},
            ),
        )


def test_flag_on_loopback_ip_advertised_exempt(fake_dns):
    # 127.0.0.1 is loopback — exempt, returns before validate_endpoint (which
    # would otherwise reject ALL raw IPs including loopback).
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "127.0.0.1:8444",
        },
    )
    assert cfg.advertised_address == "127.0.0.1:8444"


def test_flag_on_bracketed_ipv6_loopback_advertised_exempt(fake_dns):
    # Bracketed IPv6 loopback [::1]:8444 — brackets stripped, ::1 is loopback.
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "[::1]:8444",
        },
    )
    assert cfg.advertised_address == "[::1]:8444"


def test_flag_on_localhost_advertised_exempt(fake_dns):
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "localhost:8444",
        },
    )
    assert cfg.advertised_address == "localhost:8444"


def test_flag_on_schemed_advertised_resolvable_loads(fake_dns):
    # INFRA-1: a schemed advertised address (the demo/HTTP form the agent
    # registers with, e.g. ``http://gx10:8451``) strips the ``scheme://`` so the
    # host ``gx10`` is extracted and resolves — the policy passes.
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "http://gx10:8451",
        },
    )
    assert cfg.advertised_address == "http://gx10:8451"


def test_flag_on_scheme_relative_advertised_resolvable_loads(fake_dns):
    # INFRA-1: a scheme-relative advertised address (``//gx10:8451``) strips the
    # leading ``//`` so the host ``gx10`` is extracted and resolves.
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "//gx10:8451",
        },
    )
    assert cfg.advertised_address == "//gx10:8451"


def test_flag_on_schemed_advertised_no_port_resolvable_loads(fake_dns):
    # INFRA-1: a schemed advertised address with no ``:port`` after the scheme
    # strip (``http://gx10``) takes the ``else advertised`` host-extraction
    # branch (no colon remains) and resolves.
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "http://gx10",
        },
    )
    assert cfg.advertised_address == "http://gx10"


def test_flag_on_schemed_raw_ip_advertised_raises_raw_ip_error(fake_dns):
    # INFRA-1: a schemed RAW IP advertised address (``http://10.0.0.5:8451``)
    # strips the scheme, extracts ``10.0.0.5``, and is rejected as a raw IP.
    from common.name_resolution import RawIPError

    with pytest.raises(RawIPError):
        load_config(
            dotenv_path=None,
            environ={
                f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
                f"{ENV_PREFIX}ADVERTISED_ADDRESS": "http://10.0.0.5:8451",
            },
        )


def test_flag_on_broker_sentinel_advertised_exempt(fake_dns):
    # broker://<id> sentinel — exempt, passed through untouched.
    cfg = load_config(
        dotenv_path=None,
        environ={
            f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true",
            f"{ENV_PREFIX}ADVERTISED_ADDRESS": "broker://agent-1",
        },
    )
    assert cfg.advertised_address == "broker://agent-1"


def test_flag_on_broker_url_with_no_host_skips(fake_dns):
    # Flag ON but the broker URL carries no host (urlparse hostname is None ⇒
    # ""): the empty-host skip path returns without touching the resolver.
    cfg = load_config(
        dotenv_path=None,
        environ=_broker_env(
            "wss://",
            **{f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true"},
        ),
    )
    assert cfg.broker_url == "wss://"


def test_flag_on_broker_url_host_unresolvable_raises(fake_dns):
    from common.name_resolution import NameResolutionError

    with pytest.raises(NameResolutionError):
        load_config(
            dotenv_path=None,
            environ=_broker_env(
                "wss://nope.unknown:8443/x",
                **{f"{ENV_PREFIX}ENFORCE_PEER_NAME_RESOLUTION": "true"},
            ),
        )
