"""Phase 1 done-signal: an end-to-end text request through all three real apps.

Wires Router -> Registry -> Agent using in-process adapters over each app's
TestClient (no sockets, no TLS), so the full request path is exercised.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.app import create_app as create_agent
from agent.engine import EchoEngine
from common.auth import JwtVerifier
from common.protocol import Request, Response
from registry.app import create_app as create_registry
from registry.store import RegistryStore
from router.app import create_app as create_router
from router.clients import AgentNotFound, AgentUnavailable
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


class _RegistryOverTestClient:
    """RegistryClient backed by the registry's TestClient instead of httpx."""

    def __init__(self, client: TestClient):
        self._c = client

    def lookup(self, agent_id: str, token: str) -> str:
        r = self._c.get(f"/agents/{agent_id}", headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 404:
            raise AgentNotFound(agent_id)
        if r.status_code >= 400:
            raise AgentUnavailable(f"registry {r.status_code}")
        return r.json()["address"]


class _AgentOverTestClient:
    """AgentClient backed by the agent's TestClient instead of httpx."""

    def __init__(self, client: TestClient):
        self._c = client

    def infer(self, address: str, request: Request, token: str) -> Response:
        r = self._c.post(
            "/infer",
            json=request.model_dump(exclude_none=True),
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code >= 500:
            raise AgentUnavailable(f"agent {r.status_code}")
        return Response.model_validate(r.json())


class _StubClient:
    """Minimal client returning a canned error status for the adapter tests.

    Only the error paths are exercised here (success is covered by the full
    end-to-end test below), so the adapters never reach ``.json()``.
    """

    def __init__(self, status_code: int):
        self._status = status_code

    def get(self, *a, **k):
        return _StubResp(self._status)

    def post(self, *a, **k):
        return _StubResp(self._status)


class _StubResp:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_registry_adapter_maps_404_to_not_found():
    adapter = _RegistryOverTestClient(_StubClient(404))
    with pytest.raises(AgentNotFound):
        adapter.lookup("ghost", "tok")


def test_registry_adapter_maps_500_to_unavailable():
    adapter = _RegistryOverTestClient(_StubClient(500))
    with pytest.raises(AgentUnavailable):
        adapter.lookup("agent-1", "tok")


def test_agent_adapter_maps_5xx_to_unavailable():
    adapter = _AgentOverTestClient(_StubClient(503))
    req = Request.model_validate(
        {
            "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
            "type": "text",
            "content": "hi",
            "metadata": {"targetAgent": "agent-1", "authToken": "tok"},
        }
    )
    with pytest.raises(AgentUnavailable):
        adapter.infer("addr", req, "tok")


def test_end_to_end_text(tmp_path):
    verifier = _verifier()
    registry_tc = TestClient(create_registry(RegistryStore(tmp_path / "state.json"), verifier))
    agent_tc = TestClient(create_agent(EchoEngine("agent-1"), verifier))
    token = mint_test_token(secret=TEST_JWT_SECRET)

    reg = registry_tc.post(
        "/register",
        json={"agentId": "agent-1", "address": "agent-1.local:8444"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reg.status_code == 200

    router_tc = TestClient(
        create_router(
            _RegistryOverTestClient(registry_tc), _AgentOverTestClient(agent_tc), verifier
        )
    )
    resp = router_tc.post(
        "/v1/message",
        json={
            "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
            "type": "text",
            "content": "what is the price of bitcoin?",
            "metadata": {"targetAgent": "agent-1", "authToken": token},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c"
    assert body["content"] == "echo: what is the price of bitcoin?"
    assert body["metadata"]["agentId"] == "agent-1"
