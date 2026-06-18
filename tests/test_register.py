"""Agent boot-time self-registration (demo Phase 1) — no network.

Covers `agent.register` builders + `self_register` against a faked httpx client,
per `contracts/registry.openapi.yaml` (AgentRegistration).
"""

from __future__ import annotations

import datetime as _dt

import httpx
import jwt
import pytest

from agent import register
from common.config import Config, ConfigError, load_config

SECRET = "x" * 32


def _config(**overrides) -> Config:
    base = dict(
        jwt_secret=SECRET,
        agent_id="gpu-1",
        registry_host="10.0.0.2",
        registry_port=8081,
        agent_host="10.0.0.5",
        agent_port=8444,
    )
    base.update(overrides)
    return Config(**base)


class _Resp:
    def __init__(self, json_data=None, error=None):
        self._json = json_data or {}
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._json


class _Client:
    def __init__(self, resp):
        self.resp = resp
        self.posted = None
        self.closed = False

    def post(self, url, json=None, headers=None):
        self.posted = {"url": url, "json": json, "headers": headers}
        return self.resp

    def close(self):
        self.closed = True


# --- load_power_profile ----------------------------------------------------


def test_load_power_profile_none():
    assert register.load_power_profile(None) is None


def test_load_power_profile_valid(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("name: gpu-server\ncpus: 16\ngpus: all\n", encoding="utf-8")
    assert register.load_power_profile(str(p)) == {"name": "gpu-server", "cpus": 16, "gpus": "all"}


def test_load_power_profile_not_a_mapping(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- not\n- a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        register.load_power_profile(str(p))


# --- build_registration ----------------------------------------------------


def test_build_registration_defaults_address_no_caps_no_profile():
    body = register.build_registration(_config())
    assert body == {"agentId": "gpu-1", "address": "10.0.0.5:8444"}


def test_build_registration_advertised_caps_and_profile(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("name: gpu-server\ncpus: 16\n", encoding="utf-8")
    body = register.build_registration(
        _config(
            advertised_address="ext.host:9000",
            capabilities="gpu, llm , ",
            power_profile_path=str(p),
        )
    )
    assert body == {
        "agentId": "gpu-1",
        "address": "ext.host:9000",
        "capabilities": ["gpu", "llm"],
        "powerProfile": {"name": "gpu-server", "cpus": 16},
    }


# --- mint_agent_token ------------------------------------------------------


def test_mint_agent_token_explicit_and_default_now():
    fixed = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)
    token = register.mint_agent_token(_config(), now=fixed)
    # back-dated token: assert claims without enforcing the (past) expiry.
    claims = jwt.decode(
        token, SECRET, algorithms=["HS256"], issuer="bardllm-pro", options={"verify_exp": False}
    )
    assert claims["sub"] == "gpu-1"
    # default-now branch (no `now=`) must also produce a decodable token.
    token = register.mint_agent_token(_config())
    assert jwt.decode(token, SECRET, algorithms=["HS256"])["sub"] == "gpu-1"


# --- self_register ---------------------------------------------------------


def test_self_register_disabled_returns_none():
    assert register.self_register(_config(self_register=False)) is None


def test_self_register_success_with_injected_client():
    client = _Client(_Resp({"agentId": "gpu-1", "address": "10.0.0.5:8444"}))
    out = register.self_register(_config(self_register=True), client=client)
    assert out == {"agentId": "gpu-1", "address": "10.0.0.5:8444"}
    assert client.posted["url"] == "https://10.0.0.2:8081/register"
    assert client.posted["json"]["agentId"] == "gpu-1"
    assert client.posted["headers"]["Authorization"].startswith("Bearer ")
    assert client.closed is False  # injected client is not owned/closed


def test_self_register_http_error_propagates():
    client = _Client(_Resp(error=httpx.HTTPError("boom")))
    with pytest.raises(httpx.HTTPError):
        register.self_register(_config(self_register=True), client=client)


def test_self_register_requires_jwt_secret():
    with pytest.raises(ConfigError):
        register.self_register(_config(self_register=True, jwt_secret=None))


def test_self_register_owns_and_closes_default_client(monkeypatch):
    client = _Client(_Resp({"ok": True}))
    monkeypatch.setattr(register.httpx, "Client", lambda **kw: client)
    out = register.self_register(_config(self_register=True))
    assert out == {"ok": True}
    assert client.closed is True  # self-owned client is closed in finally


# --- config self_register bool coercion ------------------------------------


def test_config_self_register_bool_coercion():
    assert (
        load_config(dotenv_path=None, environ={"BARDPRO_SELF_REGISTER": "true"}).self_register
        is True
    )
    assert (
        load_config(dotenv_path=None, environ={"BARDPRO_SELF_REGISTER": "no"}).self_register
        is False
    )


# --- Sprint B2 per-device mint path (ADR-0010) -----------------------------

DEVICE_SECRET = "device-secret-padding-0123456789-abcdef"  # noqa: S105


def test_mint_agent_token_device_path_signs_with_device_secret():
    cfg = _config(device_identity_enabled=True, device_secret=DEVICE_SECRET)
    token = register.mint_agent_token(cfg)
    # Verifies under the per-device secret, sub=agent_id (the deviceId)...
    claims = jwt.decode(token, DEVICE_SECRET, algorithms=["HS256"], issuer="bardllm-pro")
    assert claims["sub"] == "gpu-1"
    # ...and NOT under the fleet secret (key isolation).
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(token, SECRET, algorithms=["HS256"])


def test_self_register_device_path_requires_device_secret():
    cfg = _config(self_register=True, device_identity_enabled=True, device_secret=None)
    with pytest.raises(ConfigError):
        register.self_register(cfg)
