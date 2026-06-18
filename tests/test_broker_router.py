"""Feature #59 / ADR-0013 — Router /v1/agent-link endpoint + broker dispatch.

Real WebSocket handshakes via starlette's TestClient (no network sockets),
covering auth-reject, malformed hellos, link replacement, dispatch-with-link
vs HTTP fallback, agent-error and timeout mapping to 502.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from common.auth import JwtVerifier
from router.app import create_app
from router.broker import BrokerLinkManager
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token
from tests.test_router import FakeAgentClient, FakeRegistryClient, _req


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _client_with_broker(
    *, manager: BrokerLinkManager | None = None, registry=None, agent=None
) -> tuple[TestClient, BrokerLinkManager]:
    manager = manager or BrokerLinkManager(timeout_s=5.0)
    app = create_app(
        registry or FakeRegistryClient(),
        agent or FakeAgentClient(),
        _verifier(),
        broker=manager,
    )
    return TestClient(app), manager


def _hello(ws, agent_id: str = "agent-1", token: str | None = None) -> None:
    token = token or mint_test_token(agent_id, secret=TEST_JWT_SECRET)
    ws.send_json({"type": "hello", "agentId": agent_id, "authToken": token})


# --- handshake ---------------------------------------------------------------


def test_agent_link_handshake_registers_and_disconnect_unregisters():
    client, manager = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws)
        assert ws.receive_json() == {"type": "hello_ok"}
        assert manager.has_link("agent-1")
    assert not manager.has_link("agent-1")


def test_agent_link_bad_token_rejected():
    client, manager = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as ws:
        ws.send_json({"type": "hello", "agentId": "agent-1", "authToken": "forged"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008
    assert not manager.has_link("agent-1")


def test_agent_link_sub_mismatch_rejected():
    # Bug #54 / H-1: a valid token whose `sub` != the claimed agentId must be
    # rejected (1008) and the link must NOT be registered.
    client, manager = _client_with_broker()
    token = mint_test_token("other-agent", secret=TEST_JWT_SECRET)
    with client.websocket_connect("/v1/agent-link") as ws:
        ws.send_json({"type": "hello", "agentId": "agent-1", "authToken": token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008
    assert not manager.has_link("agent-1")
    assert not manager.has_link("other-agent")


def test_agent_link_sub_matches_agent_id_accepted():
    # The matching case still works: sub == agentId registers the link.
    client, manager = _client_with_broker()
    token = mint_test_token("agent-1", secret=TEST_JWT_SECRET)
    with client.websocket_connect("/v1/agent-link") as ws:
        ws.send_json({"type": "hello", "agentId": "agent-1", "authToken": token})
        assert ws.receive_json() == {"type": "hello_ok"}
        assert manager.has_link("agent-1")
    assert not manager.has_link("agent-1")


def test_agent_link_malformed_hello_rejected():
    client, manager = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as ws:
        ws.send_json({"type": "hello", "agentId": ""})  # missing token, empty id
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008
    assert not manager.has_link("")


def test_agent_link_wrong_first_frame_type_rejected():
    client, _ = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as ws:
        ws.send_json({"type": "subscribe"})  # JSON, but not a hello frame
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008


def test_agent_link_non_json_hello_rejected():
    client, _ = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as ws:
        ws.send_text("definitely not json")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1003


def test_agent_link_disconnect_before_hello_is_clean():
    client, manager = _client_with_broker()
    with client.websocket_connect("/v1/agent-link"):
        pass  # client walks away without saying hello
    assert not manager.has_link("agent-1")


def test_agent_link_replacement_closes_first_socket():
    client, manager = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as first:
        _hello(first)
        assert first.receive_json() == {"type": "hello_ok"}
        with client.websocket_connect("/v1/agent-link") as second:
            _hello(second)
            assert second.receive_json() == {"type": "hello_ok"}
            with pytest.raises(WebSocketDisconnect) as exc:
                first.receive_json()  # the router closed the replaced link
            assert exc.value.code == 1012
            assert manager.has_link("agent-1")


def test_agent_link_non_json_frame_mid_stream_drops_link():
    client, manager = _client_with_broker()
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws)
        assert ws.receive_json() == {"type": "hello_ok"}
        ws.send_text("garbage mid-stream")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1003
    assert not manager.has_link("agent-1")


# --- /v1/message dispatch through the link ------------------------------------


def test_message_dispatches_through_live_link():
    # Registry knows nothing (would 404): proves the link path won.
    client, _ = _client_with_broker(registry=FakeRegistryClient(address=None))
    token = mint_test_token(secret=TEST_JWT_SECRET)
    # Enter the client so the WS session and the POST share one portal /
    # event loop — the response future must resolve on the dispatching loop.
    with client, client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws)
        assert ws.receive_json() == {"type": "hello_ok"}

        def serve_one_frame() -> None:
            frame = ws.receive_json()
            request = frame["request"]
            ws.send_json(
                {
                    "type": "infer_response",
                    "frameId": frame["frameId"],
                    "response": {
                        "id": request["id"],
                        "type": "text",
                        "content": f"broker: {request['content']}",
                        "metadata": {"agentId": "agent-1"},
                    },
                }
            )

        agent_thread = threading.Thread(target=serve_one_frame)
        agent_thread.start()
        try:
            response = client.post("/v1/message", json=_req(token))
        finally:
            agent_thread.join(timeout=5)
    assert response.status_code == 200
    assert response.json()["content"] == "broker: hi"


def test_message_agent_error_frame_maps_to_502():
    client, _ = _client_with_broker()
    token = mint_test_token(secret=TEST_JWT_SECRET)
    with client, client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws)
        assert ws.receive_json() == {"type": "hello_ok"}

        def reply_with_error() -> None:
            frame = ws.receive_json()
            ws.send_json(
                {
                    "type": "infer_error",
                    "frameId": frame["frameId"],
                    "error": {"error": "inference_failed", "retry": True},
                }
            )

        agent_thread = threading.Thread(target=reply_with_error)
        agent_thread.start()
        try:
            response = client.post("/v1/message", json=_req(token))
        finally:
            agent_thread.join(timeout=5)
    assert response.status_code == 502
    assert response.json() == {"error": "agent_unavailable", "retry": True}


def test_message_dispatch_timeout_maps_to_502():
    client, _ = _client_with_broker(manager=BrokerLinkManager(timeout_s=0))
    token = mint_test_token(secret=TEST_JWT_SECRET)
    with client, client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws)
        assert ws.receive_json() == {"type": "hello_ok"}
        # The agent never replies; timeout_s=0 trips immediately.
        response = client.post("/v1/message", json=_req(token))
    assert response.status_code == 502
    assert response.json() == {"error": "agent_unavailable", "retry": True}


def test_message_without_link_falls_back_to_http_dial():
    client, manager = _client_with_broker()
    token = mint_test_token(secret=TEST_JWT_SECRET)
    assert not manager.has_link("agent-1")
    response = client.post("/v1/message", json=_req(token))
    assert response.status_code == 200
    assert response.json()["content"] == "echo: hi"  # FakeAgentClient, direct path
