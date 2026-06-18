"""Lane C unit tests — agent HTTP app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent.app import create_app
from agent.engine import EchoEngine
from common.auth import JwtVerifier
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token


def _client() -> TestClient:
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    return TestClient(create_app(EchoEngine("agent-1"), verifier))


def _req(token: str, msg_type: str = "text") -> dict:
    return {
        "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        "type": msg_type,
        "content": "hi",
        "metadata": {"targetAgent": "agent-1", "authToken": token},
    }


def test_infer_echoes():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = _client().post("/infer", json=_req(token))
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "echo: hi"
    assert body["metadata"]["agentId"] == "agent-1"
    assert body["metadata"]["toolCalls"][0]["name"] == "echo"


def test_infer_rejects_bad_token():
    r = _client().post("/infer", json=_req("not-a-jwt"))
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"


def test_infer_voice_501():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = _client().post("/infer", json=_req(token, msg_type="voice"))
    assert r.status_code == 501 and r.json()["error"] == "unsupported_type"


def test_infer_malformed_body_400():
    r = _client().post("/infer", json={"id": "x"})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
