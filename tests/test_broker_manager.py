"""Feature #59 / ADR-0013 — BrokerLinkManager unit tests.

Register/replace/disconnect semantics, frameId-correlated dispatch, timeout
and failure mapping to AgentUnavailable, and the broker metrics — all against
an in-process fake sender (no sockets, house style: ``asyncio.run`` + fakes).
"""

from __future__ import annotations

import asyncio

import pytest

from common.metrics import AppMetrics, BrokerMetrics
from common.protocol import Request, RequestMetadata
from router.broker import AgentLink, BrokerLinkManager
from router.clients import AgentUnavailable

REQ_ID = "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c"


class FakeSender:
    """Records frames; optionally fails on send/close."""

    def __init__(
        self, *, send_error: Exception | None = None, close_error: Exception | None = None
    ):
        self.sent: list[dict] = []
        self.closed: tuple[int, str | None] | None = None
        self._send_error = send_error
        self._close_error = close_error

    async def send_json(self, data: dict) -> None:
        if self._send_error is not None:
            raise self._send_error
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        if self._close_error is not None:
            raise self._close_error
        self.closed = (code, reason)


def _request() -> Request:
    return Request(
        id=REQ_ID,
        type="text",
        content="hi",
        metadata=RequestMetadata(targetAgent="agent-1", authToken="tok"),
    )


def _response_frame(frame_id: str) -> dict:
    return {
        "type": "infer_response",
        "frameId": frame_id,
        "response": {
            "id": REQ_ID,
            "type": "text",
            "content": "echo: hi",
            "metadata": {"agentId": "agent-1"},
        },
    }


def _manager(**kwargs) -> BrokerLinkManager:
    kwargs.setdefault("timeout_s", 5.0)
    kwargs.setdefault("id_factory", lambda: "frame-1")
    return BrokerLinkManager(**kwargs)


async def _dispatch_with_reply(manager: BrokerLinkManager, link: AgentLink, reply: dict):
    """Start a dispatch, feed ``reply`` once the request frame went out."""
    task = asyncio.create_task(manager.dispatch("agent-1", _request()))
    while not link.sender.sent:  # type: ignore[attr-defined]
        await asyncio.sleep(0)
    manager.handle_frame(link, reply)
    return await task


# --- register / replace / disconnect -----------------------------------------


def test_register_and_unregister_track_links():
    async def run() -> None:
        manager = _manager()
        sender = FakeSender()
        link = await manager.register("agent-1", sender)
        assert manager.has_link("agent-1")
        manager.unregister("agent-1", link)
        assert not manager.has_link("agent-1")

    asyncio.run(run())


def test_new_connection_replaces_old_and_closes_it():
    async def run() -> None:
        manager = _manager()
        old_sender, new_sender = FakeSender(), FakeSender()
        await manager.register("agent-1", old_sender)
        new_link = await manager.register("agent-1", new_sender)
        assert old_sender.closed == (1012, "replaced by newer connection")
        assert manager.has_link("agent-1")
        # The old socket's cleanup must not drop the new link.
        manager.unregister("agent-1", AgentLink("agent-1", old_sender))
        assert manager.has_link("agent-1")
        manager.unregister("agent-1", new_link)
        assert not manager.has_link("agent-1")

    asyncio.run(run())


def test_replacement_survives_old_socket_close_failure():
    async def run() -> None:
        manager = _manager()
        await manager.register("agent-1", FakeSender(close_error=RuntimeError("already gone")))
        await manager.register("agent-1", FakeSender())
        assert manager.has_link("agent-1")

    asyncio.run(run())


def test_unregister_skips_already_done_futures():
    async def run() -> None:
        manager = _manager()
        link = await manager.register("agent-1", FakeSender())
        done: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        done.set_result({"type": "infer_response"})
        link.pending["settled"] = done  # e.g. resolved but not yet collected
        manager.unregister("agent-1", link)  # must not set_exception on it
        assert link.pending == {} and done.result()["type"] == "infer_response"

    asyncio.run(run())


def test_unregister_fails_inflight_dispatch_fast():
    async def run() -> None:
        manager = _manager()
        sender = FakeSender()
        link = await manager.register("agent-1", sender)
        task = asyncio.create_task(manager.dispatch("agent-1", _request()))
        while not sender.sent:
            await asyncio.sleep(0)
        manager.unregister("agent-1", link)
        with pytest.raises(AgentUnavailable, match="link to agent-1 lost"):
            await task

    asyncio.run(run())


# --- dispatch ------------------------------------------------------------------


def test_dispatch_round_trips_correlated_response():
    async def run():
        manager = _manager()
        link = await manager.register("agent-1", FakeSender())
        response = await _dispatch_with_reply(manager, link, _response_frame("frame-1"))
        sent = link.sender.sent[0]
        assert sent["type"] == "infer_request" and sent["frameId"] == "frame-1"
        assert sent["request"]["content"] == "hi"
        return response

    response = asyncio.run(run())
    assert response.content == "echo: hi" and response.metadata.agentId == "agent-1"


def test_dispatch_without_link_raises():
    async def run() -> None:
        with pytest.raises(AgentUnavailable, match="no live broker link"):
            await _manager().dispatch("agent-1", _request())

    asyncio.run(run())


def test_dispatch_send_failure_maps_to_unavailable():
    async def run() -> None:
        manager = _manager()
        link = await manager.register("agent-1", FakeSender(send_error=RuntimeError("pipe")))
        with pytest.raises(AgentUnavailable, match="send to agent-1 failed"):
            await manager.dispatch("agent-1", _request())
        assert link.pending == {}

    asyncio.run(run())


def test_dispatch_timeout_maps_to_unavailable():
    async def run() -> None:
        manager = _manager(timeout_s=0)
        link = await manager.register("agent-1", FakeSender())
        with pytest.raises(AgentUnavailable, match="timed out after 0s"):
            await manager.dispatch("agent-1", _request())
        assert link.pending == {}

    asyncio.run(run())


def test_dispatch_infer_error_frame_maps_to_unavailable():
    async def run() -> None:
        manager = _manager()
        link = await manager.register("agent-1", FakeSender())
        error = {
            "type": "infer_error",
            "frameId": "frame-1",
            "error": {"error": "inference_failed"},
        }
        with pytest.raises(AgentUnavailable, match="reported error"):
            await _dispatch_with_reply(manager, link, error)

    asyncio.run(run())


def test_dispatch_malformed_response_maps_to_unavailable():
    async def run() -> None:
        manager = _manager()
        link = await manager.register("agent-1", FakeSender())
        bad = {"type": "infer_response", "frameId": "frame-1", "response": {"nope": True}}
        with pytest.raises(AgentUnavailable, match="malformed broker response"):
            await _dispatch_with_reply(manager, link, bad)

    asyncio.run(run())


# --- handle_frame edge cases -----------------------------------------------------


def test_handle_frame_ignores_unknown_types_and_non_dicts(caplog):
    async def run() -> None:
        manager = _manager()
        link = await manager.register("agent-1", FakeSender())
        manager.handle_frame(link, ["not", "a", "dict"])
        manager.handle_frame(link, {"type": "weird"})
        manager.handle_frame(link, {"type": "infer_response", "frameId": "ghost"})
        manager.handle_frame(link, {"type": "infer_response"})  # missing frameId

    with caplog.at_level("WARNING"):
        asyncio.run(run())
    assert "unexpected frame" in caplog.text
    assert "unknown or stale frameId" in caplog.text


def test_handle_frame_ignores_duplicate_reply():
    async def run() -> None:
        manager = _manager()
        link = await manager.register("agent-1", FakeSender())
        task = asyncio.create_task(manager.dispatch("agent-1", _request()))
        while not link.sender.sent:  # type: ignore[attr-defined]
            await asyncio.sleep(0)
        manager.handle_frame(link, _response_frame("frame-1"))
        manager.handle_frame(link, _response_frame("frame-1"))  # stale duplicate: ignored
        assert (await task).content == "echo: hi"

    asyncio.run(run())


# --- metrics ----------------------------------------------------------------------


def test_broker_metrics_track_links_and_dispatch_outcomes():
    app_metrics = AppMetrics("router")
    metrics = BrokerMetrics(app_metrics)

    def gauge() -> float | None:
        return app_metrics.registry.get_sample_value("broker_link_active", {"agentId": "agent-1"})

    def counted(outcome: str) -> float | None:
        return app_metrics.registry.get_sample_value(
            "broker_dispatch_total", {"agentId": "agent-1", "outcome": outcome}
        )

    async def run() -> None:
        manager = _manager(metrics=metrics)
        link = await manager.register("agent-1", FakeSender())
        assert gauge() == 1.0
        await _dispatch_with_reply(manager, link, _response_frame("frame-1"))
        assert counted("ok") == 1.0
        # timeout outcome
        fast = _manager(metrics=metrics, timeout_s=0)
        await fast.register("agent-1", FakeSender())
        with pytest.raises(AgentUnavailable):
            await fast.dispatch("agent-1", _request())
        assert counted("timeout") == 1.0
        # send_failed outcome
        broken = _manager(metrics=metrics)
        await broken.register("agent-1", FakeSender(send_error=RuntimeError("pipe")))
        with pytest.raises(AgentUnavailable):
            await broken.dispatch("agent-1", _request())
        assert counted("send_failed") == 1.0
        # disconnected outcome
        drop = _manager(metrics=metrics)
        drop_link = await drop.register("agent-1", FakeSender())
        task = asyncio.create_task(drop.dispatch("agent-1", _request()))
        while not drop_link.sender.sent:  # type: ignore[attr-defined]
            await asyncio.sleep(0)
        drop.unregister("agent-1", drop_link)
        with pytest.raises(AgentUnavailable):
            await task
        assert counted("disconnected") == 1.0
        assert gauge() == 0.0
        # error outcome (agent-reported)
        err = _manager(metrics=metrics)
        err_link = await err.register("agent-1", FakeSender())
        bad = {"type": "infer_error", "frameId": "frame-1", "error": {"error": "boom"}}
        with pytest.raises(AgentUnavailable):
            await _dispatch_with_reply(err, err_link, bad)
        assert counted("error") == 1.0
        manager.unregister("agent-1", link)

    asyncio.run(run())
