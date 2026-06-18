"""Unit tests for the real outbound HTTP clients (router/clients.py).

These exercise ``HttpRegistryClient`` / ``HttpAgentClient`` against a faked
``httpx`` transport (no sockets, no network — CLAUDE.md §9). Every branch of the
agent/router contracts is covered: success, 404, generic 4xx/5xx errors, and
transport failures.
"""

from __future__ import annotations

import httpx
import pytest

from common.protocol import Request, RequestMetadata
from router import clients
from router.clients import (
    AgentNotFound,
    AgentUnavailable,
    HttpAgentClient,
    HttpRegistryClient,
    _bearer,
)


class _FakeResponse:
    """Minimal stand-in for httpx.Response with just what the clients use."""

    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def _req(target: str = "agent-1") -> Request:
    return Request(
        id="c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        type="text",
        content="hi",
        metadata=RequestMetadata(targetAgent=target, authToken="tok"),
    )


# --------------------------------------------------------------------------- #
# _bearer helper
# --------------------------------------------------------------------------- #


def test_bearer_header_format():
    assert _bearer("abc") == {"Authorization": "Bearer abc"}


# --------------------------------------------------------------------------- #
# HttpRegistryClient.lookup
# --------------------------------------------------------------------------- #


def test_registry_lookup_success(monkeypatch):
    captured: dict = {}

    def fake_get(url, *, headers, verify, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["verify"] = verify
        captured["timeout"] = timeout
        return _FakeResponse(200, {"address": "10.0.0.5:8444"})

    monkeypatch.setattr(httpx, "get", fake_get)
    client = HttpRegistryClient("https://reg.local:8081/", verify=False, timeout=5.0)
    assert client.lookup("agent-1", "tok") == "10.0.0.5:8444"
    # base_url trailing slash is stripped; path is built from the agent id.
    assert captured["url"] == "https://reg.local:8081/agents/agent-1"
    assert captured["headers"] == {"Authorization": "Bearer tok"}
    assert captured["verify"] is False
    assert captured["timeout"] == 5.0


def test_registry_lookup_404_raises_not_found(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(404))
    with pytest.raises(AgentNotFound) as exc:
        HttpRegistryClient("https://reg.local").lookup("ghost", "tok")
    assert "ghost" in str(exc.value)


# --------------------------------------------------------------------------- #
# HttpRegistryClient.from_config — honors registry_scheme (bug #60)
# --------------------------------------------------------------------------- #


def test_registry_from_config_defaults_to_https():
    from common.config import Config

    cfg = Config(jwt_secret="s" * 32, registry_host="reg.local", registry_port=8081)
    client = HttpRegistryClient.from_config(cfg, verify=False, timeout=5.0)
    assert client._base == "https://reg.local:8081"
    assert client._verify is False
    assert client._timeout == 5.0


def test_registry_from_config_honors_http_scheme():
    from common.config import Config

    cfg = Config(
        jwt_secret="s" * 32,
        registry_scheme="http",
        allow_insecure_http=True,
        registry_host="127.0.0.1",
        registry_port=8071,
    )
    # bug #60: the router must dial the registry over the *configured* scheme,
    # not a hardcoded https — else a plain-HTTP registry fails the TLS handshake
    # and every /v1/message returns 502 agent_unavailable before dispatch.
    assert HttpRegistryClient.from_config(cfg)._base == "http://127.0.0.1:8071"


def test_registry_lookup_500_raises_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(503))
    with pytest.raises(AgentUnavailable) as exc:
        HttpRegistryClient("https://reg.local").lookup("agent-1", "tok")
    assert "503" in str(exc.value)


def test_registry_lookup_transport_error_raises_unavailable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(AgentUnavailable) as exc:
        HttpRegistryClient("https://reg.local").lookup("agent-1", "tok")
    assert "unreachable" in str(exc.value)


# --------------------------------------------------------------------------- #
# HttpRegistryClient.register (slice 2 — Router relays agent registration)
# --------------------------------------------------------------------------- #


def test_registry_register_success(monkeypatch):
    captured: dict = {}

    def fake_post(url, *, json, headers, verify, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"agentId": "a1", "address": "broker://a1", "status": "active"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = HttpRegistryClient("https://reg.local:8081/", verify=False, timeout=5.0)
    out = client.register({"agentId": "a1", "address": "broker://a1"}, "tok")
    assert out["status"] == "active"
    assert captured["url"] == "https://reg.local:8081/register"
    assert captured["json"] == {"agentId": "a1", "address": "broker://a1"}
    assert captured["headers"] == {"Authorization": "Bearer tok"}


def test_registry_register_4xx_raises_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(401))
    with pytest.raises(AgentUnavailable) as exc:
        HttpRegistryClient("https://reg.local").register({"agentId": "a1", "address": "x"}, "tok")
    assert "register failed 401" in str(exc.value)


def test_registry_register_transport_error_raises_unavailable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(AgentUnavailable) as exc:
        HttpRegistryClient("https://reg.local").register({"agentId": "a1", "address": "x"}, "tok")
    assert "unreachable" in str(exc.value)


# --------------------------------------------------------------------------- #
# HttpAgentClient.infer
# --------------------------------------------------------------------------- #


def _ok_response_payload() -> dict:
    return {
        "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        "type": "text",
        "content": "echo: hi",
        "metadata": {"agentId": "agent-1"},
    }


def test_agent_infer_success_bare_host_gets_https(monkeypatch):
    captured: dict = {}

    def fake_post(url, *, json, headers, verify, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(200, _ok_response_payload())

    monkeypatch.setattr(httpx, "post", fake_post)
    resp = HttpAgentClient(verify=True, timeout=9.0).infer("agent-1.local:8444", _req(), "tok")
    assert resp.content == "echo: hi"
    # A bare host:port address is upgraded to https://.
    assert captured["url"] == "https://agent-1.local:8444/infer"
    # exclude_none drops the optional sessionId/timestamp.
    assert "sessionId" not in captured["json"]["metadata"]


def test_agent_infer_success_explicit_http_url_preserved(monkeypatch):
    captured: dict = {}

    def fake_post(url, *, json, headers, verify, timeout):
        captured["url"] = url
        return _FakeResponse(200, _ok_response_payload())

    monkeypatch.setattr(httpx, "post", fake_post)
    # An address already carrying a scheme is used verbatim.
    HttpAgentClient().infer("http://127.0.0.1:8444", _req(), "tok")
    assert captured["url"] == "http://127.0.0.1:8444/infer"


def test_agent_infer_5xx_raises_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(500))
    with pytest.raises(AgentUnavailable) as exc:
        HttpAgentClient().infer("agent-1.local:8444", _req(), "tok")
    assert "agent error 500" in str(exc.value)


def test_agent_infer_4xx_raises_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(422))
    with pytest.raises(AgentUnavailable) as exc:
        HttpAgentClient().infer("agent-1.local:8444", _req(), "tok")
    assert "rejected request: 422" in str(exc.value)


def test_agent_infer_transport_error_raises_unavailable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(AgentUnavailable) as exc:
        HttpAgentClient().infer("agent-1.local:8444", _req(), "tok")
    assert "unreachable" in str(exc.value)


def test_clients_module_exports_protocols():
    # The Protocols exist for DI/swap; smoke-check they're importable symbols.
    assert hasattr(clients, "RegistryClient")
    assert hasattr(clients, "AgentClient")
