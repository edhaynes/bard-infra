"""Agent side of the outbound broker link (feature #59 / ADR-0013).

:func:`broker_loop` runs as a background task next to the heartbeat: connect
to the Router's ``/v1/agent-link``, authenticate with a self-minted JWT (the
same one ``/register`` uses), then serve inbound ``infer_request`` frames
through the **same** :class:`InferenceEngine` the HTTP ``/infer`` path uses,
replying with ``frameId``-correlated ``infer_response`` / ``infer_error``
frames (contract: ``contracts/broker-link.schema.json``). Engine semantics
mirror ``agent/app.py`` exactly: verify the forwarded token, 501-class reject
voice, map :class:`InferenceError` to a retryable error envelope.

Link failures are logged and never fatal — the loop reconnects with
exponential backoff (``broker_backoff_initial_s`` doubling up to
``broker_backoff_max_s``, reset after a successful handshake) and exits only
on cancellation (clean shutdown via the app lifespan). The connection factory
and sleep are injectable so tests run with fakes — no real sockets, no real
waiting. The registry ``/register`` heartbeat (feature #54) is orthogonal and
untouched: it remains the liveness authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

import websockets
from pydantic import ValidationError

from agent.engine import InferenceEngine, InferenceError
from agent.register import build_link_registration, mint_agent_token
from common.auth import AuthError, TokenVerifier
from common.config import Config
from common.protocol import ProtocolError, Request

logger = logging.getLogger(__name__)


class BrokerHandshakeError(RuntimeError):
    """The Router did not acknowledge the hello frame."""


class WireConnection(Protocol):
    """Text-frame duplex socket (``websockets`` client connection fits)."""

    async def send(self, data: str) -> None: ...

    async def recv(self) -> str: ...


#: ``connector(url)`` returns an async context manager yielding a connection —
#: exactly the shape of ``websockets.connect``.
Connector = Callable[[str], AbstractAsyncContextManager[WireConnection]]


def _ssl_context(config: Config, url: str) -> ssl.SSLContext | None:
    """Custom CA (``tls_cert_path``) for wss URLs; None -> library defaults."""
    if not url.startswith("wss://") or not config.tls_cert_path:
        return None
    return ssl.create_default_context(cafile=config.tls_cert_path)


def default_connector(config: Config) -> Connector:
    """Production connector: ``websockets.connect`` with optional custom CA."""

    def connect(url: str) -> AbstractAsyncContextManager[WireConnection]:
        ctx = _ssl_context(config, url)
        if ctx is not None:
            return websockets.connect(url, ssl=ctx)
        return websockets.connect(url)

    return connect


def serve_frame(
    frame: object, engine: InferenceEngine, verifier: TokenVerifier, agent_id: str
) -> dict | None:
    """Serve one inbound frame; return the reply frame (None = nothing to send).

    Mirrors the HTTP ``/infer`` handler: same auth check on the forwarded
    token, same voice rejection, same engine, same error envelopes.
    """
    if not isinstance(frame, dict) or frame.get("type") != "infer_request":
        logger.warning("broker: ignoring unexpected frame", extra={"agentId": agent_id})
        return None
    frame_id = frame.get("frameId")
    if not isinstance(frame_id, str) or not frame_id:
        logger.warning("broker: infer_request without frameId", extra={"agentId": agent_id})
        return None
    try:
        request = Request.model_validate(frame.get("request"))
    except ValidationError:
        return _error_frame(frame_id, "bad_request")
    try:
        verifier.verify(request.metadata.authToken)
    except AuthError:
        return _error_frame(frame_id, "unauthorized")
    if request.type == "voice":
        return _error_frame(frame_id, "unsupported_type", detail="voice not supported in MVP")
    try:
        response = engine.infer(request)
    except InferenceError as exc:
        return _error_frame(frame_id, "inference_failed", retry=True, detail=str(exc))
    return {
        "type": "infer_response",
        "frameId": frame_id,
        "response": response.model_dump(exclude_none=True),
    }


def _error_frame(
    frame_id: str, error: str, *, retry: bool = False, detail: str | None = None
) -> dict:
    body = ProtocolError(error=error, retry=retry, detail=detail).model_dump(exclude_none=True)
    return {"type": "infer_error", "frameId": frame_id, "error": body}


async def _handshake(config: Config, connection: WireConnection) -> None:
    token = mint_agent_token(config)
    await connection.send(
        json.dumps({"type": "hello", "agentId": config.agent_id, "authToken": token})
    )
    reply = json.loads(await connection.recv())
    if not isinstance(reply, dict) or reply.get("type") != "hello_ok":
        raise BrokerHandshakeError(f"unexpected handshake reply: {reply!r}")


async def _register_over_link(config: Config, connection: WireConnection) -> None:
    """Send the initial register frame after hello_ok (slice 2 / single front
    door). No-op when self-registration is off — broker mode owns registration
    only when the agent is meant to advertise itself."""
    if not config.self_register:
        return
    frame = {"type": "register", **build_link_registration(config)}
    await connection.send(json.dumps(frame))
    logger.info("broker: sent register frame", extra={"agentId": config.agent_id})


async def _heartbeat_sender(
    config: Config,
    connection: WireConnection,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Send a heartbeat frame every ``heartbeat_interval_s`` so the Registry's
    ``lastSeen`` stays fresh over the link (slice 2). A heartbeat IS a /register
    refresh — identical body, identical TTL semantics (feature #54). No-op when
    self-registration is off; loops until the connection drops (a send raising
    propagates out and ends the session)."""
    if not config.self_register:
        return
    while True:
        await sleep(config.heartbeat_interval_s)
        frame = {"type": "heartbeat", **build_link_registration(config)}
        await connection.send(json.dumps(frame))


async def _serve(
    connection: WireConnection,
    engine: InferenceEngine,
    verifier: TokenVerifier,
    agent_id: str,
) -> None:
    """Pump frames until the connection drops (raises out to the reconnect loop)."""
    while True:
        frame = json.loads(await connection.recv())
        # The engine is sync (same as the HTTP path); keep the link responsive.
        reply = await asyncio.to_thread(serve_frame, frame, engine, verifier, agent_id)
        if reply is not None:
            await connection.send(json.dumps(reply))


async def _run_session(
    config: Config,
    connection: WireConnection,
    engine: InferenceEngine,
    verifier: TokenVerifier,
    heartbeat_sleep: Callable[[float], Awaitable[None]],
) -> None:
    """One live link: register, then serve infer frames and send heartbeats
    concurrently. The first task to finish (serve raising on link drop)
    cancels the other; the original failure propagates to the reconnect loop."""
    await _register_over_link(config, connection)
    serve = asyncio.ensure_future(_serve(connection, engine, verifier, config.agent_id))
    beat = asyncio.ensure_future(_heartbeat_sender(config, connection, heartbeat_sleep))
    done, pending = await asyncio.wait({serve, beat}, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    # Re-raise the failure that ended the session so the reconnect loop backs
    # off. ``FIRST_EXCEPTION`` guarantees at least one finished task raised
    # (serve never returns cleanly while the link is up; the heartbeat only
    # ends by raising on a send), so this re-raise always fires.
    failed = next(task for task in done if task.exception() is not None)
    failed.result()


async def broker_loop(
    config: Config,
    engine: InferenceEngine,
    verifier: TokenVerifier,
    *,
    connector: Connector | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    heartbeat_sleep: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    """Maintain the outbound link forever (see module docstring).

    ``sleep`` paces reconnect backoff; ``heartbeat_sleep`` paces the over-link
    heartbeat cadence (both injectable so tests run with no real waiting)."""
    connect = connector or default_connector(config)
    do_sleep = sleep or asyncio.sleep
    do_heartbeat_sleep = heartbeat_sleep or asyncio.sleep
    backoff = config.broker_backoff_initial_s
    while True:
        try:
            async with connect(config.broker_url) as connection:
                await _handshake(config, connection)
                backoff = config.broker_backoff_initial_s  # link is good: reset
                logger.info("broker link up", extra={"url": config.broker_url})
                await _run_session(config, connection, engine, verifier, do_heartbeat_sleep)
        except Exception as exc:  # any link failure -> log with context, back off, retry
            logger.warning(
                "broker link down, reconnecting",
                extra={"url": config.broker_url, "backoff_s": backoff, "error": str(exc)},
            )
        await do_sleep(backoff)
        backoff = min(backoff * 2, config.broker_backoff_max_s)
