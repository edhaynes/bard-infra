"""Feature #59 / ADR-0013 — agent-side broker link.

The reconnect loop with an injected connector + sleep (no sockets, no
waiting), frame servicing through the same EchoEngine as the HTTP path,
backoff growth/cap/reset, the broker config gates, and the app lifespan
running the broker task.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from agent import broker
from agent.app import create_app as create_agent_app
from agent.engine import EchoEngine, InferenceError
from common.auth import JwtVerifier
from common.config import ConfigError, load_config
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token
from tests.test_liveness import _CancellingSleep

REQ_ID = "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c"
WSS_URL = "wss://router.local:9443/v1/agent-link"


def _cfg(**overrides):
    base: dict = {
        "agent_id": "agent-1",
        "jwt_secret": TEST_JWT_SECRET,
        "broker_enabled": True,
        "broker_url": WSS_URL,
        # These tests exercise the broker loop/config gates, not the peer
        # name-resolution policy (default ON since the flag was flipped). The
        # ``router.local`` peer URL is a hermetic placeholder that intentionally
        # does not resolve, so opt OUT of enforcement explicitly here.
        "enforce_peer_name_resolution": False,
    }
    base.update(overrides)
    return load_config(dotenv_path=None, environ={}, cli_overrides=base)


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _infer_frame(frame_id: str = "frame-1", msg_type: str = "text", token: str | None = None):
    return {
        "type": "infer_request",
        "frameId": frame_id,
        "request": {
            "id": REQ_ID,
            "type": msg_type,
            "content": "hi",
            "metadata": {
                "targetAgent": "agent-1",
                "authToken": token or mint_test_token(secret=TEST_JWT_SECRET),
            },
        },
    }


class FakeConnection:
    """Scripted duplex socket: hello -> hello_ok (or a bad reply), then the
    preloaded frames; recv on an empty inbox raises like a dropped link."""

    def __init__(self, frames: list[object] | None = None, *, accept: bool = True):
        self.sent: list[dict] = []
        self._accept = accept
        self._frames = list(frames or [])
        self._inbox: list[str] = []

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def send(self, data: str) -> None:
        message = json.loads(data)
        self.sent.append(message)
        if message.get("type") == "hello":
            reply = {"type": "hello_ok"} if self._accept else {"type": "go_away"}
            self._inbox.append(json.dumps(reply))
            self._inbox.extend(json.dumps(f) for f in self._frames)

    async def recv(self) -> str:
        if self._inbox:
            return self._inbox.pop(0)
        raise OSError("connection closed")


class FakeConnector:
    """Yields each plan item per connect call: a connection, or an exception
    to raise at dial time. An exhausted plan keeps failing."""

    def __init__(self, plan: list[object]):
        self._plan = list(plan)
        self.calls = 0

    def __call__(self, url: str):
        self.calls += 1
        item = self._plan.pop(0) if self._plan else OSError("dial failed")
        if isinstance(item, Exception):
            raise item
        return item


def _run_loop(config, connector, sleep) -> None:
    async def run() -> None:
        engine = EchoEngine("agent-1")
        await broker.broker_loop(config, engine, _verifier(), connector=connector, sleep=sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())


# --- serve_frame: same semantics as the HTTP /infer path -------------------------


def test_serve_frame_runs_engine_and_correlates():
    reply = broker.serve_frame(_infer_frame(), EchoEngine("agent-1"), _verifier(), "agent-1")
    assert reply["type"] == "infer_response" and reply["frameId"] == "frame-1"
    assert reply["response"]["content"] == "echo: hi"
    assert reply["response"]["metadata"]["agentId"] == "agent-1"


def test_serve_frame_rejects_bad_token():
    frame = _infer_frame(token="forged")
    reply = broker.serve_frame(frame, EchoEngine("agent-1"), _verifier(), "agent-1")
    assert reply["type"] == "infer_error" and reply["error"]["error"] == "unauthorized"


def test_serve_frame_rejects_voice():
    reply = broker.serve_frame(_infer_frame(msg_type="voice"), EchoEngine("a"), _verifier(), "a")
    assert reply["type"] == "infer_error" and reply["error"]["error"] == "unsupported_type"


def test_serve_frame_rejects_malformed_request():
    frame = {"type": "infer_request", "frameId": "frame-1", "request": {"bogus": 1}}
    reply = broker.serve_frame(frame, EchoEngine("a"), _verifier(), "a")
    assert reply["type"] == "infer_error" and reply["error"]["error"] == "bad_request"


def test_serve_frame_maps_engine_failure():
    class FailingEngine:
        def infer(self, request):
            raise InferenceError("model melted")

    reply = broker.serve_frame(_infer_frame(), FailingEngine(), _verifier(), "agent-1")
    assert reply["type"] == "infer_error"
    assert reply["error"] == {"error": "inference_failed", "retry": True, "detail": "model melted"}


def test_serve_frame_ignores_noise(caplog):
    with caplog.at_level(logging.WARNING):
        assert broker.serve_frame("not a dict", EchoEngine("a"), _verifier(), "a") is None
        assert broker.serve_frame({"type": "weird"}, EchoEngine("a"), _verifier(), "a") is None
        no_id = {"type": "infer_request", "request": {}}
        assert broker.serve_frame(no_id, EchoEngine("a"), _verifier(), "a") is None
        empty_id = {"type": "infer_request", "frameId": "", "request": {}}
        assert broker.serve_frame(empty_id, EchoEngine("a"), _verifier(), "a") is None
    assert "unexpected frame" in caplog.text and "without frameId" in caplog.text


# --- broker_loop: connect, serve, reconnect ----------------------------------------


def test_loop_serves_frames_through_engine():
    connection = FakeConnection(frames=[{"type": "noise"}, _infer_frame()])
    sleep = _CancellingSleep(allowed=0)  # first backoff sleep cancels the loop
    _run_loop(_cfg(), FakeConnector([connection]), sleep)
    hello, response = connection.sent
    assert hello["type"] == "hello" and hello["agentId"] == "agent-1"
    assert hello["authToken"]  # minted JWT rides the hello frame
    assert response["type"] == "infer_response" and response["frameId"] == "frame-1"
    assert response["response"]["content"] == "echo: hi"


def test_loop_backoff_doubles_and_caps(caplog):
    sleep = _CancellingSleep(allowed=4)
    config = _cfg(broker_backoff_initial_s=1.0, broker_backoff_max_s=4.0)
    with caplog.at_level(logging.WARNING):
        _run_loop(config, FakeConnector([]), sleep)  # every dial fails
    assert sleep.intervals == [1.0, 2.0, 4.0, 4.0]
    assert "broker link down, reconnecting" in caplog.text


def test_loop_backoff_resets_after_successful_handshake():
    plan = [OSError("dial failed"), FakeConnection()]  # fail, then connect+drop
    sleep = _CancellingSleep(allowed=2)
    _run_loop(_cfg(broker_backoff_initial_s=1.0), FakeConnector(plan), sleep)
    assert sleep.intervals == [1.0, 1.0]  # second failure backs off from initial again


def test_loop_handshake_rejection_backs_off(caplog):
    connection = FakeConnection(accept=False)
    with caplog.at_level(logging.WARNING):
        _run_loop(_cfg(), FakeConnector([connection]), _CancellingSleep(allowed=0))
    # The cause travels in the log record's structured ``error`` extra.
    errors = [getattr(record, "error", "") for record in caplog.records]
    assert any("unexpected handshake reply" in e for e in errors)
    assert [m["type"] for m in connection.sent] == ["hello"]  # nothing served


def test_loop_default_connector_and_sleep_paths(monkeypatch):
    """connector=None -> default_connector -> websockets.connect (patched to a
    fake: no sockets); sleep=None -> real asyncio.sleep at 0s backoff."""
    connections: list[FakeConnection] = []

    def fake_connect(url, **kwargs):
        assert url == WSS_URL and not kwargs  # no custom CA configured
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(broker.websockets, "connect", fake_connect)
    config = _cfg(broker_backoff_initial_s=0.0, broker_backoff_max_s=0.0)

    async def run() -> None:
        task = asyncio.create_task(broker.broker_loop(config, EchoEngine("agent-1"), _verifier()))
        while len(connections) < 2:  # survived one full connect->drop->reconnect cycle
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert connections[0].sent[0]["type"] == "hello"


# --- default connector TLS wiring ---------------------------------------------------


def test_ssl_context_only_for_wss_with_custom_ca(tmp_path):
    import trustme

    ca_path = tmp_path / "ca.pem"
    trustme.CA().cert_pem.write_to_path(str(ca_path))
    with_ca = _cfg(tls_cert_path=str(ca_path))
    assert broker._ssl_context(with_ca, WSS_URL) is not None
    assert broker._ssl_context(with_ca, "ws://router.local/v1/agent-link") is None
    assert broker._ssl_context(_cfg(), WSS_URL) is None


def test_default_connector_builds_websockets_client(tmp_path):
    import trustme

    ca_path = tmp_path / "ca.pem"
    trustme.CA().cert_pem.write_to_path(str(ca_path))
    # Instantiation only — websockets dials at __aenter__, never here.
    assert broker.default_connector(_cfg())(WSS_URL) is not None
    assert broker.default_connector(_cfg(tls_cert_path=str(ca_path)))(WSS_URL) is not None


# --- agent app lifespan runs the broker task ------------------------------------------


def test_agent_app_starts_and_cancels_broker_task():
    state = {"started": False, "cancelled": False}

    async def broker_task() -> None:
        state["started"] = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    from fastapi.testclient import TestClient

    app = create_agent_app(EchoEngine("agent-1"), _verifier(), broker=broker_task)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert state["started"] is True
    assert state["cancelled"] is True


# --- config gates ---------------------------------------------------------------------


def test_broker_config_defaults_off():
    config = load_config(dotenv_path=None, environ={})
    assert config.broker_enabled is False and config.broker_url is None
    assert config.broker_backoff_initial_s == 1.0 and config.broker_backoff_max_s == 60.0


def test_broker_config_coerces_from_env():
    config = load_config(
        dotenv_path=None,
        environ={
            "BARDPRO_BROKER_ENABLED": "true",
            "BARDPRO_BROKER_URL": WSS_URL,
            "BARDPRO_BROKER_BACKOFF_INITIAL_S": "0.5",
            "BARDPRO_BROKER_BACKOFF_MAX_S": "30",
            # Not testing the peer policy; the placeholder host does not resolve.
            "BARDPRO_ENFORCE_PEER_NAME_RESOLUTION": "false",
        },
    )
    assert config.broker_enabled is True and config.broker_url == WSS_URL
    assert config.broker_backoff_initial_s == 0.5 and config.broker_backoff_max_s == 30.0


def test_broker_enabled_requires_url():
    with pytest.raises(ConfigError, match="BARDPRO_BROKER_URL"):
        _cfg(broker_url=None)


def test_broker_plain_ws_requires_insecure_opt_in(caplog):
    with pytest.raises(ConfigError, match="cleartext"):
        _cfg(broker_url="ws://router.local/v1/agent-link")
    with caplog.at_level(logging.WARNING):
        config = _cfg(broker_url="ws://router.local/v1/agent-link", allow_insecure_http=True)
    assert config.broker_url.startswith("ws://")
    assert "INSECURE TRANSPORT" in caplog.text


def test_broker_rejects_non_ws_scheme():
    with pytest.raises(ConfigError, match="must be wss://"):
        _cfg(broker_url="https://router.local/v1/agent-link")
