"""Targeted tests closing the remaining branch-coverage gaps.

These exercise small, previously-untested branches across the product modules:
auth (empty-secret guard, from_config, issuer-less verify), power-profile valid
memory, version resolution fallback, identity signing, store with no persistence
path, and the un-hit health/version/error endpoints on each FastAPI app.
"""

from __future__ import annotations

import datetime as _dt

import jwt
import pytest
from fastapi.testclient import TestClient

from agent.app import create_app as create_agent_app
from agent.engine import EchoEngine
from common.auth import AuthError, JwtVerifier
from common.config import Config
from common.power import PowerProfile
from common.version import _resolve_version
from registry.app import create_app as create_registry_app
from registry.store import RegistryStore
from router.app import create_app as create_router_app
from router.clients import AgentUnavailable
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token
from trust.identity import Identity

# --------------------------------------------------------------------------- #
# common/auth.py
# --------------------------------------------------------------------------- #


def test_jwt_verifier_rejects_empty_secret():
    with pytest.raises(ValueError, match="JWT secret is required"):
        JwtVerifier("")


def test_jwt_verifier_from_config():
    cfg = Config(jwt_secret=TEST_JWT_SECRET, jwt_algorithm="HS256", jwt_issuer="bardllm-pro")
    verifier = JwtVerifier.from_config(cfg)
    claims = verifier.verify(mint_test_token("alice", secret=TEST_JWT_SECRET))
    assert claims["sub"] == "alice"


def test_jwt_verifier_without_issuer_skips_issuer_check():
    # issuer=None -> the verify path must NOT require an issuer claim.
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", issuer=None)
    claims = verifier.verify(mint_test_token("bob", secret=TEST_JWT_SECRET))
    assert claims["sub"] == "bob"


def test_jwt_verifier_bad_token_raises_auth_error():
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    with pytest.raises(AuthError):
        verifier.verify("garbage.token.value")


def _mint_claims(claims: dict) -> str:
    return jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")


@pytest.mark.parametrize("missing", ["exp", "iss", "sub"])
def test_jwt_verifier_requires_exp_iss_sub(missing):
    # Finding M-1: a token lacking any of exp/iss/sub must be rejected. In
    # particular a token with no `exp` would otherwise never expire.
    now = _dt.datetime.now(_dt.UTC)
    claims = {
        "sub": "agent-1",
        "iss": "bardllm-pro",
        "iat": now,
        "exp": now + _dt.timedelta(hours=1),
    }
    del claims[missing]
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    with pytest.raises(AuthError):
        verifier.verify(_mint_claims(claims))


def test_jwt_verifier_complete_token_passes():
    now = _dt.datetime.now(_dt.UTC)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    claims = verifier.verify(
        _mint_claims(
            {
                "sub": "agent-1",
                "iss": "bardllm-pro",
                "iat": now,
                "exp": now + _dt.timedelta(hours=1),
            }
        )
    )
    assert claims["sub"] == "agent-1"


def test_jwt_verifier_expired_token_rejected():
    # Well past any leeway window.
    now = _dt.datetime.now(_dt.UTC)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    with pytest.raises(AuthError):
        verifier.verify(
            _mint_claims(
                {
                    "sub": "agent-1",
                    "iss": "bardllm-pro",
                    "iat": now - _dt.timedelta(hours=2),
                    "exp": now - _dt.timedelta(hours=1),
                }
            )
        )


# --------------------------------------------------------------------------- #
# common/power.py
# --------------------------------------------------------------------------- #


def test_power_profile_accepts_valid_memory():
    assert PowerProfile(name="p", memory="2g").memory == "2g"


def test_power_profile_accepts_none_memory():
    assert PowerProfile(name="p").memory is None


def test_power_profile_rejects_bad_memory():
    with pytest.raises(ValueError, match="memory must match"):
        PowerProfile(name="p", memory="lots")


# --------------------------------------------------------------------------- #
# common/version.py
# --------------------------------------------------------------------------- #


def test_resolve_version_reads_version_file():
    # In a source checkout the adjacent VERSION file wins.
    assert _resolve_version() != "0.0.0"


def test_resolve_version_falls_back_to_metadata(monkeypatch):
    import common.version as version_mod

    # Force the "no adjacent VERSION file" branch.
    monkeypatch.setattr(version_mod.Path, "is_file", lambda self: False)
    monkeypatch.setattr(version_mod, "_pkg_version", lambda name: "9.9.9")
    assert _resolve_version() == "9.9.9"


def test_resolve_version_metadata_missing_returns_zero(monkeypatch):
    import common.version as version_mod

    def _raise(name):
        raise version_mod.PackageNotFoundError(name)

    monkeypatch.setattr(version_mod.Path, "is_file", lambda self: False)
    monkeypatch.setattr(version_mod, "_pkg_version", _raise)
    assert _resolve_version() == "0.0.0"


# --------------------------------------------------------------------------- #
# trust/identity.py
# --------------------------------------------------------------------------- #


def test_identity_sign_is_deterministic_for_same_input():
    ident = Identity.generate("alice")
    sig1 = ident.sign(b"payload")
    sig2 = ident.sign(b"payload")
    assert sig1 == sig2
    assert sig1 != ident.sign(b"other")
    assert len(sig1) == 64  # sha256 hexdigest


# --------------------------------------------------------------------------- #
# registry/store.py — no-persistence path (state_path=None)
# --------------------------------------------------------------------------- #


def test_store_without_path_does_not_persist():
    store = RegistryStore(None)
    store.register("a1", "10.0.0.1:8444")
    assert store.get("a1")["address"] == "10.0.0.1:8444"


# --------------------------------------------------------------------------- #
# FastAPI health/version endpoints + uncovered error branches
# --------------------------------------------------------------------------- #


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


class _UnavailableRegistry:
    def lookup(self, agent_id: str, token: str) -> str:
        raise AgentUnavailable("registry down")


class _UnusedAgent:
    def infer(self, address, request, token):  # pragma: no cover - never reached
        raise AssertionError("should not be called")


def _router_client(registry, agent) -> TestClient:
    return TestClient(create_router_app(registry, agent, _verifier()))


def test_router_registry_unavailable_returns_502():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    client = _router_client(_UnavailableRegistry(), _UnusedAgent())
    r = client.post(
        "/v1/message",
        json={
            "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
            "type": "text",
            "content": "hi",
            "metadata": {"targetAgent": "agent-1", "authToken": token},
        },
    )
    assert r.status_code == 502
    assert r.json()["error"] == "agent_unavailable" and r.json()["retry"] is True


def test_router_validation_error_returns_400():
    client = _router_client(_UnavailableRegistry(), _UnusedAgent())
    # Missing required fields triggers the RequestValidationError handler.
    r = client.post("/v1/message", json={"type": "text"})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_router_health_and_version():
    client = _router_client(_UnavailableRegistry(), _UnusedAgent())
    assert client.get("/healthz").json() == {"status": "ok"}
    assert "version" in client.get("/version").json()


def _registry_client(tmp_path) -> TestClient:
    return TestClient(create_registry_app(RegistryStore(tmp_path / "s.json"), _verifier()))


def test_registry_register_requires_auth(tmp_path):
    r = _registry_client(tmp_path).post("/register", json={"agentId": "a", "address": "x:1"})
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"


def test_registry_list_requires_auth(tmp_path):
    r = _registry_client(tmp_path).get("/agents")
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"


def test_registry_list_returns_agents(tmp_path):
    client = _registry_client(tmp_path)
    client.post("/register", json={"agentId": "a1", "address": "x:1"}, headers=_auth())
    r = client.get("/agents", headers=_auth())
    assert r.status_code == 200 and len(r.json()) == 1


def test_registry_health_and_version(tmp_path):
    client = _registry_client(tmp_path)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert "version" in client.get("/version").json()


def _agent_client() -> TestClient:
    return TestClient(create_agent_app(EchoEngine("agent-1"), _verifier()))


def test_agent_health_and_version():
    client = _agent_client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert "version" in client.get("/version").json()
