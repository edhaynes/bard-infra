"""Router side of the outbound-agent broker link (feature #59 / ADR-0013).

:class:`BrokerLinkManager` keeps the in-memory map of live agent links — one
per ``agentId``, a newer connection replaces the older one — and correlates
dispatched ``infer_request`` frames with their ``infer_response`` /
``infer_error`` replies by ``frameId``. State is process-local: the same
single-instance constraint the JSON-file registry already imposes on v1
(multi-instance routers arrive with the Valkey control plane, ADR-0010).

:func:`handle_agent_link` is the ``/v1/agent-link`` WebSocket handler: it
authenticates the agent's hello frame with the injected ``TokenVerifier``
(the same seam ``/v1/message`` uses), registers the link, and pumps reply
frames into the manager until the socket drops. Frame shapes are contract:
``contracts/broker-link.schema.json``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from common.auth import AuthError, TokenVerifier
from common.metrics import BrokerMetrics
from common.protocol import Request, Response
from router.clients import AgentUnavailable, RegistryClient

logger = logging.getLogger(__name__)

#: Close codes (RFC 6455): 1003 unsupported data, 1008 policy violation,
#: 1012 service restart — used for "replaced by a newer connection".
CLOSE_UNSUPPORTED_DATA = 1003
CLOSE_POLICY_VIOLATION = 1008
CLOSE_REPLACED = 1012

#: Sentinel scheme for the advertisedAddress of a broker-linked agent (slice 2):
#: the agent is reachable down its link, never by dialing an address. The Router
#: synthesizes ``broker://<agentId>`` so the registry record carries a stable,
#: non-dialable address; /v1/message always prefers the live link over it, and
#: placement/pool key off powerProfile/capabilities/status, not the address.
BROKER_ADDRESS_SCHEME = "broker://"


class LinkSender(Protocol):
    """What the manager needs from a live socket (starlette WebSocket fits)."""

    async def send_json(self, data: dict) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class AgentLink:
    """One live agent connection plus its in-flight dispatch futures.

    ``auth_token`` is the JWT the agent presented in its hello (already
    verified). The Router reuses it to authorize the agent's relayed
    registrations against the Registry's existing bearer auth — exactly the
    token the agent would have sent on a direct HTTP ``/register``.
    """

    def __init__(self, agent_id: str, sender: LinkSender, auth_token: str = ""):
        self.agent_id = agent_id
        self.sender = sender
        self.auth_token = auth_token
        self.pending: dict[str, asyncio.Future[dict]] = {}


class BrokerLinkManager:
    """In-memory registry of live links + correlated request/response dispatch."""

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        metrics: BrokerMetrics | None = None,
        id_factory: Callable[[], str] | None = None,
    ):
        self._links: dict[str, AgentLink] = {}
        self._timeout_s = timeout_s
        self._metrics = metrics
        self._next_id = id_factory or (lambda: uuid.uuid4().hex)

    def has_link(self, agent_id: str) -> bool:
        return agent_id in self._links

    async def register(self, agent_id: str, sender: LinkSender, auth_token: str = "") -> AgentLink:
        """Adopt a new link; a previous link for the same agent is replaced
        (its pending dispatches fail fast, its socket is closed)."""
        old = self._links.get(agent_id)
        if old is not None:
            self.unregister(agent_id, old)
            with contextlib.suppress(Exception):  # best-effort close of a dying socket
                await old.sender.close(CLOSE_REPLACED, reason="replaced by newer connection")
        link = AgentLink(agent_id, sender, auth_token)
        self._links[agent_id] = link
        if self._metrics:
            self._metrics.link_active.labels(agentId=agent_id).set(1)
        logger.info("broker link up", extra={"agentId": agent_id})
        return link

    def unregister(self, agent_id: str, link: AgentLink) -> None:
        """Drop ``link`` if it is still the current one and fail its in-flight
        dispatches immediately (no point waiting out the timeout)."""
        if self._links.get(agent_id) is link:
            del self._links[agent_id]
            if self._metrics:
                self._metrics.link_active.labels(agentId=agent_id).set(0)
            logger.info("broker link down", extra={"agentId": agent_id})
        for future in link.pending.values():
            if not future.done():
                future.set_exception(AgentUnavailable(f"broker link to {agent_id} lost"))
        link.pending.clear()

    def handle_frame(self, link: AgentLink, frame: object) -> None:
        """Resolve an agent reply frame against its pending dispatch."""
        if not isinstance(frame, dict) or frame.get("type") not in (
            "infer_response",
            "infer_error",
        ):
            logger.warning("broker: ignoring unexpected frame", extra={"agentId": link.agent_id})
            return
        future = link.pending.get(frame.get("frameId") or "")
        if future is None or future.done():
            logger.warning(
                "broker: reply for unknown or stale frameId",
                extra={"agentId": link.agent_id, "frameId": frame.get("frameId")},
            )
            return
        future.set_result(frame)

    async def dispatch(self, agent_id: str, request: Request) -> Response:
        """Send ``request`` down the agent's link and await the correlated
        reply. Raises :class:`AgentUnavailable` (the caller's 502) on a missing
        link, send failure, agent-reported error, malformed reply, link loss,
        or timeout."""
        link = self._links.get(agent_id)
        if link is None:
            raise AgentUnavailable(f"no live broker link for {agent_id}")
        frame_id = self._next_id()
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        link.pending[frame_id] = future
        try:
            await link.sender.send_json(
                {
                    "type": "infer_request",
                    "frameId": frame_id,
                    "request": request.model_dump(exclude_none=True),
                }
            )
        except Exception as exc:  # send failed -> the link is dead; log + 502
            link.pending.pop(frame_id, None)
            self._count(agent_id, "send_failed")
            logger.warning(
                "broker dispatch send failed", extra={"agentId": agent_id, "error": str(exc)}
            )
            raise AgentUnavailable(f"broker send to {agent_id} failed: {exc}") from exc
        try:
            frame = await asyncio.wait_for(future, timeout=self._timeout_s)
        except TimeoutError as exc:
            self._count(agent_id, "timeout")
            raise AgentUnavailable(
                f"broker dispatch to {agent_id} timed out after {self._timeout_s}s"
            ) from exc
        except AgentUnavailable:  # link dropped mid-flight (unregister failed the future)
            self._count(agent_id, "disconnected")
            raise
        finally:
            link.pending.pop(frame_id, None)
        if frame["type"] == "infer_error":
            # Parity with the HTTP-dial path: any agent-side error maps to
            # 502 agent_unavailable retry:true at /v1/message.
            self._count(agent_id, "error")
            raise AgentUnavailable(f"agent {agent_id} reported error: {frame.get('error')}")
        try:
            response = Response.model_validate(frame.get("response"))
        except ValidationError as exc:
            self._count(agent_id, "error")
            raise AgentUnavailable(f"malformed broker response from {agent_id}") from exc
        self._count(agent_id, "ok")
        logger.info("broker dispatch ok", extra={"agentId": agent_id, "frameId": frame_id})
        return response

    def _count(self, agent_id: str, outcome: str) -> None:
        if self._metrics:
            self._metrics.dispatch.labels(agentId=agent_id, outcome=outcome).inc()


def build_relay_body(agent_id: str, frame: dict) -> dict:
    """Build the ``/register`` body for a register/heartbeat frame (slice 2).

    The ``agentId`` is the link's authenticated identity — **never** read from
    the frame (a frame-supplied agentId is ignored; the contract forbids one,
    and this is the defense-in-depth for bug #54). ``advertisedAddress``
    defaults to the ``broker://<agentId>`` sentinel when the frame omits it.
    ``capabilities`` / ``powerProfile`` pass through verbatim to the Registry,
    which validates the profile exactly as on the HTTP path.
    """
    address = frame.get("advertisedAddress") or f"{BROKER_ADDRESS_SCHEME}{agent_id}"
    body: dict = {"agentId": agent_id, "address": address}
    caps = frame.get("capabilities")
    if caps:
        body["capabilities"] = caps
    profile = frame.get("powerProfile")
    if profile is not None:
        body["powerProfile"] = profile
    return body


async def relay_registration(link: AgentLink, frame: dict, registry: RegistryClient) -> bool:
    """Forward a register/heartbeat frame to the Registry's ``/register`` bound
    to the link's authenticated agentId. Returns True on success.

    A heartbeat frame is treated identically to a register frame: it refreshes
    the Registry's ``lastSeen`` (feature #54 TTL semantics unchanged). Registry
    failures are logged and swallowed — the link stays up and the next
    heartbeat retries; if registrations keep failing, the agent simply goes
    stale by the normal TTL (no second liveness path).
    """
    body = build_relay_body(link.agent_id, frame)
    try:
        # RegistryClient is sync httpx; keep the link's event loop responsive.
        await asyncio.to_thread(registry.register, body, link.auth_token)
    except AgentUnavailable as exc:
        logger.warning(
            "broker: registry relay failed",
            extra={"agentId": link.agent_id, "kind": frame.get("type"), "error": str(exc)},
        )
        return False
    logger.info(
        "broker: relayed registration",
        extra={"agentId": link.agent_id, "kind": frame.get("type")},
    )
    with contextlib.suppress(Exception):  # best-effort ack; agent does not block on it
        await link.sender.send_json({"type": "registered"})
    return True


def _parse_hello(hello: object) -> tuple[str, str] | None:
    """Return (agentId, authToken) from a well-formed hello frame, else None."""
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        return None
    agent_id, token = hello.get("agentId"), hello.get("authToken")
    if not isinstance(agent_id, str) or not agent_id or not isinstance(token, str) or not token:
        return None
    return agent_id, token


async def _route_link_frame(
    link: AgentLink,
    frame: object,
    manager: BrokerLinkManager,
    registry: RegistryClient | None,
) -> None:
    """Dispatch one agent->router frame: register/heartbeat relay to the
    Registry (slice 2), else infer reply correlation (slice 1)."""
    if (
        registry is not None
        and isinstance(frame, dict)
        and frame.get("type") in ("register", "heartbeat")
    ):
        await relay_registration(link, frame, registry)
        return
    manager.handle_frame(link, frame)


async def handle_agent_link(
    websocket: WebSocket,
    manager: BrokerLinkManager,
    verifier: TokenVerifier,
    registry: RegistryClient | None = None,
) -> None:
    """Serve one agent connection on ``/v1/agent-link`` (see module docstring).

    When ``registry`` is provided (slice 2 / single front door), register and
    heartbeat frames from the agent are relayed to the Registry's ``/register``
    bound to the link's authenticated agentId; otherwise only infer-reply
    frames are handled (slice 1 behavior, unchanged).
    """
    await websocket.accept()
    try:
        hello = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    except ValueError:  # non-JSON first frame
        await websocket.close(CLOSE_UNSUPPORTED_DATA, reason="expected JSON hello frame")
        return
    parsed = _parse_hello(hello)
    if parsed is None:
        await websocket.close(CLOSE_POLICY_VIOLATION, reason="malformed hello frame")
        return
    agent_id, token = parsed
    try:
        claims = verifier.verify(token)
    except AuthError:
        logger.warning("broker: rejected agent link (bad token)", extra={"agentId": agent_id})
        await websocket.close(CLOSE_POLICY_VIOLATION, reason="unauthorized")
        return
    # Bind the verified token identity to the claimed agentId (bug #54 / H-1).
    # Under the shared-fleet-secret model any valid token would otherwise be
    # able to claim any agentId and hijack its dispatched inferences.
    if claims.get("sub") != agent_id:
        logger.warning(
            "broker: rejected agent link (sub != agentId)",
            extra={"agentId": agent_id, "sub": claims.get("sub")},
        )
        await websocket.close(CLOSE_POLICY_VIOLATION, reason="unauthorized")
        return
    link = await manager.register(agent_id, websocket, token)
    try:
        await websocket.send_json({"type": "hello_ok"})
        while True:
            await _route_link_frame(link, await websocket.receive_json(), manager, registry)
    except WebSocketDisconnect:
        pass
    except ValueError:  # non-JSON frame mid-stream: drop the link
        with contextlib.suppress(RuntimeError):  # socket may already be gone
            await websocket.close(CLOSE_UNSUPPORTED_DATA, reason="expected JSON frames")
    finally:
        manager.unregister(agent_id, link)
