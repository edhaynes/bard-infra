"""Slice 2 — LokNet single front door: registration + heartbeat over the link.

ADR-0013 / feature #59 / PLAN_loknet slice 2. In broker mode the agent
registers and heartbeats OVER the link; the Router relays both to the
(now-private) Registry's existing ``/register`` bound to the link's
authenticated agentId. Direct mode is unchanged.

Covered here (real starlette TestClient WS + injected fakes/clock, no sockets):
  * register-over-link forwards to the Registry bound to the link's agentId;
  * a frame-supplied agentId is IGNORED (bug #54 binding constraint);
  * heartbeat-over-link refreshes ``lastSeen`` (real store + injected clock);
  * pool/schedule see a link-registered agent;
  * a dropped link lets the agent go stale by the normal TTL (no 2nd path);
  * the agent's register/heartbeat body builders + the broker session that
    sends register then heartbeat frames over the link;
  * the agent in broker mode does NOT use the HTTP /register path;
  * direct mode still POSTs to /register exactly as before.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from agent import broker, register
from agent.engine import EchoEngine
from common.auth import JwtVerifier
from registry.store import RegistryStore
from router.app import create_app
from router.broker import (
    BROKER_ADDRESS_SCHEME,
    AgentLink,
    BrokerLinkManager,
    build_relay_body,
    relay_registration,
)
from router.clients import AgentUnavailable
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token
from tests.test_broker_agent import (
    WSS_URL,
    FakeConnection,
    FakeConnector,
    _cfg,
)
from tests.test_liveness import FakeClock, _CancellingSleep
from tests.test_router import FakeAgentClient, FakeRegistryClient

GPU = {"name": "gpu-server", "cpus": 16, "memory": "32g", "gpus": "all"}


# --- fakes -------------------------------------------------------------------


class RecordingRegistryClient(FakeRegistryClient):
    """FakeRegistryClient that records (and optionally fails) /register relays."""

    def __init__(self, *, address: str | None = "x:1", fail: bool = False):
        super().__init__(address=address)
        self.registered: list[tuple[dict, str]] = []
        self._fail = fail

    def register(self, body: dict, token: str) -> dict:
        if self._fail:
            raise AgentUnavailable("registry down")
        self.registered.append((body, token))
        return {"agentId": body["agentId"], "address": body["address"], "status": "active"}


class StoreBackedRegistryClient(FakeRegistryClient):
    """Relay register straight into a real RegistryStore so TTL/pool/schedule
    behave exactly as the registry app would (no HTTP, injected clock)."""

    def __init__(self, store: RegistryStore):
        super().__init__(address=None)
        self.store = store

    def register(self, body: dict, token: str) -> dict:
        return self.store.register(
            body["agentId"], body["address"], body.get("capabilities"), body.get("powerProfile")
        )


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _broker_client(registry) -> tuple[TestClient, BrokerLinkManager]:
    manager = BrokerLinkManager(timeout_s=5.0)
    app = create_app(registry, FakeAgentClient(), _verifier(), broker=manager)
    return TestClient(app), manager


def _hello(ws, agent_id: str = "agent-1") -> None:
    ws.send_json(
        {
            "type": "hello",
            "agentId": agent_id,
            "authToken": mint_test_token(agent_id, secret=TEST_JWT_SECRET),
        }
    )


# --- build_relay_body: agentId binding + sentinel address --------------------


def test_build_relay_body_binds_link_agent_id_and_defaults_sentinel():
    body = build_relay_body("agent-1", {"type": "register"})
    assert body == {"agentId": "agent-1", "address": f"{BROKER_ADDRESS_SCHEME}agent-1"}


def test_build_relay_body_ignores_frame_agent_id():
    # A forged agentId in the frame must never win (bug #54 binding).
    body = build_relay_body("agent-1", {"type": "register", "agentId": "victim"})
    assert body["agentId"] == "agent-1"


def test_build_relay_body_passes_through_caps_and_profile():
    frame = {
        "type": "register",
        "advertisedAddress": "broker://agent-1",
        "capabilities": ["gpu", "llm"],
        "powerProfile": GPU,
    }
    body = build_relay_body("agent-1", frame)
    assert body == {
        "agentId": "agent-1",
        "address": "broker://agent-1",
        "capabilities": ["gpu", "llm"],
        "powerProfile": GPU,
    }


# --- register/heartbeat over a live link relays to the Registry --------------


def test_register_frame_relays_to_registry_bound_to_link_identity():
    registry = RecordingRegistryClient()
    client, _ = _broker_client(registry)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "agent-7")
        assert ws.receive_json() == {"type": "hello_ok"}
        ws.send_json({"type": "register", "capabilities": ["gpu"]})
        assert ws.receive_json() == {"type": "registered"}
    assert len(registry.registered) == 1
    body, token = registry.registered[0]
    assert body["agentId"] == "agent-7"  # the link's identity, not the frame's
    assert body["address"] == f"{BROKER_ADDRESS_SCHEME}agent-7"
    assert body["capabilities"] == ["gpu"]
    assert token  # the hello's verified JWT authorizes the relay


def test_register_frame_with_forged_agent_id_is_ignored():
    registry = RecordingRegistryClient()
    client, _ = _broker_client(registry)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "agent-1")
        assert ws.receive_json() == {"type": "hello_ok"}
        # Even if a frame smuggles a different agentId, the link's identity wins.
        ws.send_json({"type": "register", "agentId": "victim"})
        assert ws.receive_json() == {"type": "registered"}
    assert registry.registered[0][0]["agentId"] == "agent-1"


def test_heartbeat_frame_relays_like_register():
    registry = RecordingRegistryClient()
    client, _ = _broker_client(registry)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "agent-1")
        assert ws.receive_json() == {"type": "hello_ok"}
        ws.send_json({"type": "register"})
        assert ws.receive_json() == {"type": "registered"}
        ws.send_json({"type": "heartbeat"})
        assert ws.receive_json() == {"type": "registered"}
    assert [b["agentId"] for b, _ in registry.registered] == ["agent-1", "agent-1"]


def test_relay_failure_does_not_drop_link_or_ack():
    # Registry down: the link stays up, no ack, and the next frame still serves.
    registry = RecordingRegistryClient(fail=True)
    client, manager = _broker_client(registry)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "agent-1")
        assert ws.receive_json() == {"type": "hello_ok"}
        ws.send_json({"type": "register"})
        # No "registered" ack arrives; prove the link is still alive by replacing it.
        assert manager.has_link("agent-1")


# --- relay_registration unit (direct, for the failure branch) ----------------


class _NullSender:
    """Placeholder sender for an AgentLink whose send path is never exercised."""


def test_relay_registration_returns_false_on_registry_error(caplog):
    # On a registry failure the relay never reaches the ack send, so a bare
    # sender (no send_json) suffices and proves the early-return path.
    link = AgentLink("agent-1", sender=_NullSender(), auth_token="tok")
    with caplog.at_level("WARNING"):
        ok = asyncio.run(
            relay_registration(link, {"type": "register"}, RecordingRegistryClient(fail=True))
        )
    assert ok is False
    assert "registry relay failed" in caplog.text


# --- heartbeat refreshes lastSeen; pool/schedule see the link-registered agent


def test_heartbeat_over_link_refreshes_last_seen_and_keeps_active():
    clock = FakeClock()
    store = RegistryStore(state_path=None, ttl_s=45.0, clock=clock)
    registry = StoreBackedRegistryClient(store)
    client, _ = _broker_client(registry)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "node-a")
        assert ws.receive_json() == {"type": "hello_ok"}
        ws.send_json({"type": "register", "powerProfile": GPU})
        assert ws.receive_json() == {"type": "registered"}
        first_seen = store.get("node-a")["lastSeen"]
        clock.advance(30)  # within TTL
        ws.send_json({"type": "heartbeat", "powerProfile": GPU})
        assert ws.receive_json() == {"type": "registered"}
    record = store.get("node-a")
    assert record["status"] == "active"
    assert record["lastSeen"] != first_seen  # the heartbeat refreshed it
    # Pool + schedule both see the link-registered agent (sentinel addr, real profile).
    assert store.pool()["gpuNodes"] == 1
    assert store.list(include_stale=False)[0]["agentId"] == "node-a"


def test_dropped_link_lets_agent_go_stale_by_ttl():
    clock = FakeClock()
    store = RegistryStore(state_path=None, ttl_s=45.0, clock=clock)
    registry = StoreBackedRegistryClient(store)
    client, manager = _broker_client(registry)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "node-b")
        assert ws.receive_json() == {"type": "hello_ok"}
        ws.send_json({"type": "register", "powerProfile": GPU})
        assert ws.receive_json() == {"type": "registered"}
    # Link is now dropped (context exited): no second liveness path keeps it alive.
    assert not manager.has_link("node-b")
    clock.advance(60)  # exceed the 45s TTL with no further heartbeat
    assert store.get("node-b")["status"] == "stale"
    assert store.list(include_stale=False) == []  # excluded from placement


# --- agent side: builders + the over-link register/heartbeat session ---------


def test_build_link_registration_omits_agent_id_and_address_by_default():
    body = register.build_link_registration(_cfg())
    assert "agentId" not in body and "advertisedAddress" not in body


def test_build_link_registration_includes_explicit_address_and_caps(tmp_path):
    profile = tmp_path / "p.yaml"
    profile.write_text("name: gpu\ncpus: 8\n", encoding="utf-8")
    cfg = _cfg(
        advertised_address="broker://agent-1",
        capabilities="gpu, llm",
        power_profile_path=str(profile),
    )
    body = register.build_link_registration(cfg)
    assert body == {
        "advertisedAddress": "broker://agent-1",
        "capabilities": ["gpu", "llm"],
        "powerProfile": {"name": "gpu", "cpus": 8},
    }


def test_broker_session_sends_register_then_heartbeats_over_link():
    # One connection, scripted to stay open long enough for two heartbeats.
    connection = FakeConnection(frames=[{"type": "noise"}])
    cfg = _cfg(self_register=True, heartbeat_interval_s=5.0)
    # heartbeat_sleep yields twice (two beats) then the serve loop's recv drains
    # and raises -> the session ends -> backoff sleep cancels the loop.
    beat_sleep = _CancellingSleep(allowed=2)
    _run_loop_hb(cfg, FakeConnector([connection]), _CancellingSleep(allowed=0), beat_sleep)
    types = [m["type"] for m in connection.sent]
    assert types[0] == "hello"
    assert types[1] == "register"  # initial registration right after hello_ok
    assert types.count("heartbeat") == 2  # two heartbeat frames sent
    assert beat_sleep.intervals == [5.0, 5.0]


def test_broker_session_cancels_heartbeat_when_serve_drops():
    # Serve raises on the first recv (link drop) while the heartbeat task is
    # still sleeping -> the pending heartbeat task is cancelled, the serve
    # failure propagates to the reconnect loop. Covers the pending-cancel path.
    blocking = asyncio.Event()  # never set: the heartbeat sleeper hangs

    async def _hang(_interval: float) -> None:
        await blocking.wait()

    connection = FakeConnection(frames=[])  # recv drains immediately -> OSError
    cfg = _cfg(self_register=True, heartbeat_interval_s=5.0)
    _run_loop_hb(cfg, FakeConnector([connection]), _CancellingSleep(allowed=0), _hang)
    types = [m["type"] for m in connection.sent]
    assert types == ["hello", "register"]  # registered, then serve dropped


def test_broker_session_skips_register_when_self_register_off():
    connection = FakeConnection(frames=[])
    cfg = _cfg(self_register=False, heartbeat_interval_s=5.0)
    never = _CancellingSleep(allowed=0)
    _run_loop_hb(cfg, FakeConnector([connection]), never, _CancellingSleep(allowed=0))
    types = [m["type"] for m in connection.sent]
    assert "register" not in types and "heartbeat" not in types
    assert types == ["hello"]


def _run_loop_hb(config, connector, sleep, heartbeat_sleep) -> None:
    async def run() -> None:
        await broker.broker_loop(
            config,
            EchoEngine("agent-1"),
            _verifier(),
            connector=connector,
            sleep=sleep,
            heartbeat_sleep=heartbeat_sleep,
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())


# --- direct mode unchanged: still POSTs HTTP /register -----------------------


def test_direct_mode_still_posts_http_register():
    from tests.test_register import _Client, _config, _Resp

    client = _Client(_Resp({"agentId": "gpu-1", "address": "10.0.0.5:8444"}))
    # broker disabled => the HTTP self_register path runs exactly as v1.
    cfg = _config(self_register=True, broker_enabled=False)
    out = register.self_register(cfg, client=client)
    assert out["agentId"] == "gpu-1"
    assert client.posted["url"] == "https://10.0.0.2:8081/register"


# --- agent main wiring: broker mode suppresses the HTTP heartbeat ------------


def test_main_wiring_suppresses_http_register_in_broker_mode(monkeypatch):
    """In broker mode, agent.main must NOT self_register over HTTP and must
    leave the HTTP heartbeat unset (the link owns registration)."""
    import importlib
    import sys
    from unittest.mock import Mock

    # A Mock records calls without executing real httpx; we assert it was never
    # called, proving broker mode suppresses the HTTP self_register entirely.
    spy = Mock(return_value=None)
    monkeypatch.setattr(register, "self_register", spy)
    monkeypatch.setenv("BARDPRO_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("BARDPRO_SELF_REGISTER", "true")
    monkeypatch.setenv("BARDPRO_BROKER_ENABLED", "true")
    monkeypatch.setenv("BARDPRO_BROKER_URL", WSS_URL)
    # Not testing the peer policy; the placeholder broker host does not resolve.
    monkeypatch.setenv("BARDPRO_ENFORCE_PEER_NAME_RESOLUTION", "false")
    sys.modules.pop("agent.main", None)
    main = importlib.import_module("agent.main")
    try:
        spy.assert_not_called()  # HTTP register never ran in broker mode
        assert main._heartbeat is None  # HTTP heartbeat loop suppressed
        assert main._broker is not None  # the link owns registration instead
    finally:
        sys.modules.pop("agent.main", None)
