"""Sprint 1 / 1a — LlamaCppEngine + engine selection.

No network: the llama.cpp OpenAI-compatible server is faked with
``httpx.MockTransport`` (CLAUDE.md §9).
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.app import create_app
from agent.engine import (
    EchoEngine,
    InferenceError,
    LlamaCppEngine,
    make_engine,
)
from common.auth import JwtVerifier
from common.config import Config, ConfigError
from common.protocol import Request, RequestMetadata
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token


def _request(content: str = "say hi") -> Request:
    return Request(
        id="11111111-1111-4111-8111-111111111111",
        type="text",
        content=content,
        metadata=RequestMetadata(targetAgent="agent-1", authToken="t"),
    )


def _engine_with(handler) -> LlamaCppEngine:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://llama/v1")
    return LlamaCppEngine("agent-1", "http://llama/v1", "tiny-gguf", client=client)


def test_llamacpp_maps_completion_to_response():
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "tiny-gguf"
        assert payload["messages"][0]["content"] == "say hi"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hello there"}}]},
        )

    resp = _engine_with(handler).infer(_request())
    assert resp.content == "hello there"
    assert resp.type == "text"
    assert resp.metadata.agentId == "agent-1"
    assert resp.metadata.toolCalls == []  # llama path carries no demo toolCalls


def test_llamacpp_backend_unreachable_raises_inference_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(InferenceError):
        _engine_with(handler).infer(_request())


def test_llamacpp_http_500_raises_inference_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(InferenceError):
        _engine_with(handler).infer(_request())


def test_llamacpp_malformed_completion_raises_inference_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(InferenceError):
        _engine_with(handler).infer(_request())


def test_make_engine_selects_backend():
    assert isinstance(make_engine(Config(inference_backend="echo")), EchoEngine)
    assert isinstance(make_engine(Config(inference_backend="llamacpp")), LlamaCppEngine)
    # vLLM is OpenAI-compatible -> same engine, wired from the vllm_* config.
    vllm = make_engine(Config(inference_backend="vllm"))
    assert isinstance(vllm, LlamaCppEngine)
    assert vllm.model == "Qwen/Qwen3-0.6B"
    assert vllm._label == "vLLM"


def test_vllm_backend_label_surfaces_in_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    engine = LlamaCppEngine(
        "agent-1", "http://vllm/v1", "Qwen/Qwen3-0.6B", client=client, backend_label="vLLM"
    )
    with pytest.raises(InferenceError, match="vLLM"):
        engine.infer(_request())


def test_make_engine_rejects_unknown_backend():
    with pytest.raises(ConfigError):
        make_engine(Config(inference_backend="bogus"))


def test_agent_app_returns_llamacpp_completion_end_to_end():
    """Full Python path: /infer -> JWT -> LlamaCppEngine -> (mocked) llama server."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "the answer is 42"}}]})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://llama/v1")
    engine = LlamaCppEngine("agent-1", "http://llama/v1", "tiny-gguf", client=http)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    client = TestClient(create_app(engine, verifier))
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = client.post(
        "/infer",
        json={
            "id": "33333333-3333-4333-8333-333333333333",
            "type": "text",
            "content": "what is the answer?",
            "metadata": {"targetAgent": "agent-1", "authToken": token},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "the answer is 42"
    assert body["metadata"]["agentId"] == "agent-1"


def test_agent_app_maps_inference_error_to_502():
    """app.py wraps engine failures in the retryable error envelope."""

    class FailingEngine:
        def infer(self, request):  # noqa: ARG002
            raise InferenceError("backend down")

    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    client = TestClient(create_app(FailingEngine(), verifier))
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = client.post(
        "/infer",
        json={
            "id": "22222222-2222-4222-8222-222222222222",
            "type": "text",
            "content": "hi",
            "metadata": {"targetAgent": "agent-1", "authToken": token},
        },
    )
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "inference_failed" and body["retry"] is True
