"""Inference engine behind an interface.

Two engines implement the same :class:`InferenceEngine` protocol and drop in
without touching the HTTP layer (CLAUDE.md §2):

* ``EchoEngine`` — echo + a demo toolCall, mirroring the FakeAgent (tests/dev).
* ``LlamaCppEngine`` — talks to a llama.cpp **OpenAI-compatible** server
  co-located with the agent (``/v1/chat/completions``) over httpx.

The backend is selected from config (``inference_backend``) by
:func:`make_engine`, so the agent serves a real model without the HTTP app
knowing which engine is wired in. (ADR-0003: the agent fronts an
OpenAI-compatible llama.cpp server; LiteLLM's multi-backend routing lives at the
Router, not inside the agent image.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import httpx

from common.protocol import Request, Response, ResponseMetadata, ToolCall, ToolResult

if TYPE_CHECKING:
    from common.config import Config


class InferenceError(RuntimeError):
    """The backend model could not produce a completion. Mapped to a retryable
    ``inference_failed`` error envelope by the agent app."""


class InferenceEngine(Protocol):
    def infer(self, request: Request) -> Response: ...


class EchoEngine:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def infer(self, request: Request) -> Response:
        return Response(
            id=request.id,
            type="text",
            content=f"echo: {request.content}",
            metadata=ResponseMetadata(
                agentId=self.agent_id,
                sessionId=request.metadata.sessionId,
                toolCalls=[ToolCall(name="echo", arguments={"content": request.content})],
                toolResults=[ToolResult(name="echo", output=request.content)],
            ),
        )


class LlamaCppEngine:
    """Forwards a text request to a llama.cpp OpenAI-compatible server.

    The ``client`` is injectable for testing (CLAUDE.md §2); in production it
    defaults to an httpx client pointed at ``base_url`` (e.g.
    ``http://127.0.0.1:8080/v1``).
    """

    def __init__(
        self,
        agent_id: str,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        backend_label: str = "llama.cpp",
    ):
        self.agent_id = agent_id
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Both llama.cpp and vLLM are OpenAI-compatible, so this one forwarder
        # serves both; the label just makes the error name the real backend.
        self._label = backend_label
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout, headers=headers)

    def infer(self, request: Request) -> Response:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.content}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        try:
            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise InferenceError(f"{self._label} backend unreachable: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise InferenceError(f"malformed completion from backend: {exc}") from exc

        return Response(
            id=request.id,
            type="text",
            content=content,
            metadata=ResponseMetadata(
                agentId=self.agent_id,
                sessionId=request.metadata.sessionId,
            ),
        )


def make_engine(config: Config) -> InferenceEngine:
    """Select the inference engine from config (CLAUDE.md §1 — no hardcoding)."""
    backend = config.inference_backend
    if backend == "echo":
        return EchoEngine(config.agent_id)
    if backend == "llamacpp":
        return LlamaCppEngine(
            config.agent_id,
            config.llama_base_url,
            config.llama_model,
            api_key=config.llama_api_key,
            max_tokens=config.inference_max_tokens,
            temperature=config.inference_temperature,
            timeout=config.request_timeout_s,
        )
    if backend == "vllm":
        # vLLM is OpenAI-compatible — same forwarder, vLLM's server + config.
        return LlamaCppEngine(
            config.agent_id,
            config.vllm_base_url,
            config.vllm_model,
            api_key=config.vllm_api_key,
            max_tokens=config.inference_max_tokens,
            temperature=config.inference_temperature,
            timeout=config.request_timeout_s,
            backend_label="vLLM",
        )
    # Import locally to avoid a module-level config dependency in the engine.
    from common.config import ConfigError

    raise ConfigError(
        f"Unknown BARDPRO_INFERENCE_BACKEND={backend!r} (expected 'echo', 'llamacpp', or 'vllm')"
    )
