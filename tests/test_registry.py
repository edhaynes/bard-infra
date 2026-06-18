"""Lane B unit tests — registry store + HTTP app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.store import AgentNotFound, RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _client(tmp_path) -> TestClient:
    store = RegistryStore(tmp_path / "state.json")
    return TestClient(create_app(store, _verifier()))


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def test_store_register_get_list(tmp_path):
    store = RegistryStore(tmp_path / "s.json")
    store.register("a1", "10.0.0.1:8444", capabilities=["llm"])
    assert store.get("a1")["address"] == "10.0.0.1:8444"
    assert len(store.list()) == 1


def test_store_unknown_raises(tmp_path):
    with pytest.raises(AgentNotFound):
        RegistryStore(tmp_path / "s.json").get("nope")


def test_store_persists_across_restart(tmp_path):
    path = tmp_path / "s.json"
    RegistryStore(path).register("a1", "10.0.0.1:8444")
    reloaded = RegistryStore(path)
    assert reloaded.get("a1")["address"] == "10.0.0.1:8444"


def test_store_invalid_power_profile_rejected(tmp_path):
    from pydantic import ValidationError

    store = RegistryStore(tmp_path / "s.json")
    with pytest.raises(ValidationError):
        store.register("a1", "10.0.0.1:8444", power_profile={"name": "x", "memory": "lots"})


def test_app_register_and_lookup(tmp_path):
    client = _client(tmp_path)
    r = client.post(
        "/register", json={"agentId": "a1", "address": "10.0.0.1:8444"}, headers=_auth()
    )
    assert r.status_code == 200
    r = client.get("/agents/a1", headers=_auth())
    assert r.status_code == 200 and r.json()["address"] == "10.0.0.1:8444"


def test_app_requires_auth(tmp_path):
    r = _client(tmp_path).get("/agents/a1")
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"


def test_app_unknown_agent_404(tmp_path):
    r = _client(tmp_path).get("/agents/nope", headers=_auth())
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_app_bad_power_profile_400(tmp_path):
    client = _client(tmp_path)
    r = client.post(
        "/register",
        json={"agentId": "a1", "address": "x:1", "powerProfile": {"name": "p", "cpus": -1}},
        headers=_auth(),
    )
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
