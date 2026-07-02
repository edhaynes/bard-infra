"""Two-node routing over bardnet (LokNet, ADR-0013): the Router dispatches an
inference to the CORRECT node when TWO agents hold live broker links.

The real-model proof (two Ollama-backed agents) lives in
``scripts/smoke_two_node_infer.py``; that needs Ollama and real sockets, so it is
operational tooling. This is its hermetic regression companion: no network, no
model — a fake agent side that echoes back its own ``agentId`` — asserting the
routing invariant the smoke depends on. A request targeting ``node-a`` is served
by ``node-a``; a request targeting ``node-b`` is served by ``node-b``; the two
links never cross.

Modelled on ``tests/test_broker_router.py::test_message_dispatches_through_live_link``.
"""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from router.app import create_app
from router.broker import BrokerLinkManager
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token
from tests.test_router import FakeAgentClient, FakeRegistryClient, _req


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _hello(ws, agent_id: str) -> None:
    ws.send_json(
        {
            "type": "hello",
            "agentId": agent_id,
            "authToken": mint_test_token(agent_id, secret=TEST_JWT_SECRET),
        }
    )
    assert ws.receive_json() == {"type": "hello_ok"}


def _serve_one_tagged(ws) -> None:
    """One-shot fake agent: reply to the next infer_request with a completion
    tagged by the frame's own target — i.e. this link's agentId, so the response
    proves which node served it."""
    frame = ws.receive_json()
    request = frame["request"]
    ws.send_json(
        {
            "type": "infer_response",
            "frameId": frame["frameId"],
            "response": {
                "id": request["id"],
                "type": "text",
                "content": f"served:{request['content']}",
                "metadata": {"agentId": request["metadata"]["targetAgent"]},
            },
        }
    )


def test_router_routes_to_the_targeted_node_among_two_live_links():
    """FROZEN behaviour: with node-a AND node-b both linked, routing is by
    ``targetAgent`` — each request is served by the node it names, never the
    other. This is the invariant the two-node LLM smoke relies on."""
    # Registry knows nothing (would 404): proves both requests took the link path.
    manager = BrokerLinkManager(timeout_s=5.0)
    app = create_app(
        FakeRegistryClient(address=None), FakeAgentClient(), _verifier(), broker=manager
    )
    client = TestClient(app)
    token = mint_test_token(secret=TEST_JWT_SECRET)

    with (
        client,
        client.websocket_connect("/v1/agent-link") as ws_a,
        client.websocket_connect("/v1/agent-link") as ws_b,
    ):
        _hello(ws_a, "node-a")
        _hello(ws_b, "node-b")
        assert manager.has_link("node-a")
        assert manager.has_link("node-b")

        # Route to node-a: only node-a's link should be served.
        thread_a = threading.Thread(target=_serve_one_tagged, args=(ws_a,))
        thread_a.start()
        try:
            resp_a = client.post("/v1/message", json=_req(token, target="node-a"))
        finally:
            thread_a.join(timeout=5)

        # Route to node-b: only node-b's link should be served.
        thread_b = threading.Thread(target=_serve_one_tagged, args=(ws_b,))
        thread_b.start()
        try:
            resp_b = client.post("/v1/message", json=_req(token, target="node-b"))
        finally:
            thread_b.join(timeout=5)

    assert resp_a.status_code == 200
    assert resp_a.json()["metadata"]["agentId"] == "node-a"
    assert resp_b.status_code == 200
    assert resp_b.json()["metadata"]["agentId"] == "node-b"
