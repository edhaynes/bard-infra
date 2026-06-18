"""FastAPI app for the Router / Talk Service (router.openapi.yaml).

Flow: validate JWT in metadata.authToken -> reject voice (501) -> if the
target agent holds a live broker link (feature #59 / ADR-0013), dispatch the
request down it; otherwise look up targetAgent in the registry (404) and
forward over the direct HTTP dial (502 on failure) -> relay the JSON
response. The broker is optional and additive: with ``broker=None`` the app
is exactly the v1 surface.

The Registry lookup is an internal Router->Registry hop; when a ``service_tokens``
minter is injected the Router authenticates that hop with its own fleet token
(bug #63) instead of forwarding the caller's per-device credential, which the
fleet-only Registry would reject. With ``service_tokens=None`` the caller's
token is forwarded (the v1 behavior).

Box ping (Step S6 / ADR-0016): a channel member pushes a one-way ``box.ping``
to every OTHER member that holds a live broker link. The delivery rail is the
same broker that carries inference (``/v1/agent-link`` registers a device's live
WS keyed by its deviceId == token ``sub``), but a ping is a fan-out push with no
reply — :meth:`BrokerLinkManager.send`, not :meth:`dispatch`. Membership and
ownership come from the injected :class:`ChannelStore` (shared with the
Registry); the endpoint is registered only when a channel store is wired.
"""

from __future__ import annotations

import asyncio
import datetime as _dt

from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocket

from common.auth import AuthError, TokenMinter, TokenVerifier
from common.cors import apply_cors
from common.errors import error_response
from common.metrics import AppMetrics, instrument
from common.protocol import Request
from common.version import __version__
from registry.channel_store import ChannelStore
from router.broker import BrokerLinkManager, handle_agent_link
from router.clients import AgentClient, AgentNotFound, AgentUnavailable, RegistryClient


def _bearer(authorization: str | None) -> str:
    """Extract the bearer token from an Authorization header (the ping endpoint
    is a plain REST call, authed by header — not the in-body authToken the
    /v1/message protocol envelope carries)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def create_app(
    registry_client: RegistryClient,
    agent_client: AgentClient,
    verifier: TokenVerifier,
    *,
    cors_origins: list[str] | None = None,
    metrics: AppMetrics | None = None,
    broker: BrokerLinkManager | None = None,
    service_tokens: TokenMinter | None = None,
    channel_store: ChannelStore | None = None,
) -> FastAPI:
    app = FastAPI(title="Bard Router", version=__version__)
    apply_cors(app, cors_origins)
    instrument(app, metrics or AppMetrics("router"))

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_request, _exc):
        return error_response(400, "bad_request")

    @app.post("/v1/message")
    async def post_message(request: Request):
        token = request.metadata.authToken
        try:
            verifier.verify(token)
        except AuthError:
            return error_response(401, "unauthorized")

        if request.type == "voice":
            return error_response(501, "unsupported_type", detail="voice not supported in MVP")

        target = request.metadata.targetAgent
        if broker is not None and broker.has_link(target):
            # Outbound-agent broker path (ADR-0013): no registry address
            # needed — the agent is reachable down its own link.
            try:
                response = await broker.dispatch(target, request)
            except AgentUnavailable:
                return error_response(502, "agent_unavailable", retry=True)
            return JSONResponse(content=response.model_dump(exclude_none=True))

        # Direct-dial path, unchanged from v1. The clients are sync httpx, so
        # they run off the event loop now that this handler is async.
        #
        # Bug #63: the registry lookup is an INTERNAL Router->Registry call, and
        # the Registry gates /agents fleet-only. Authenticate it with the
        # Router's own fleet service token (when a minter is wired) rather than
        # forwarding the caller's credential — otherwise a per-device caller,
        # accepted at /v1/message above, is rejected at this hop (401 -> 502).
        # The caller's identity still rides to the agent on the infer hop below.
        lookup_token = service_tokens.token() if service_tokens is not None else token
        try:
            address = await asyncio.to_thread(registry_client.lookup, target, lookup_token)
        except AgentNotFound:
            return error_response(404, "not_found")
        except AgentUnavailable:
            return error_response(502, "agent_unavailable", retry=True)

        try:
            response = await asyncio.to_thread(agent_client.infer, address, request, token)
        except AgentUnavailable:
            return error_response(502, "agent_unavailable", retry=True)

        return JSONResponse(content=response.model_dump(exclude_none=True))

    if broker is not None:

        @app.websocket("/v1/agent-link")
        async def agent_link(websocket: WebSocket):
            # Pass the registry client so register/heartbeat frames are relayed
            # to /register on the agent's behalf (slice 2 / ADR-0013 single
            # front door): the Registry needs no public bind in broker mode.
            await handle_agent_link(websocket, broker, verifier, registry_client)

        # --- Box ping (Step S6 / ADR-0016) -----------------------------------
        # A channel member pushes a one-way "box.ping" to every OTHER member
        # that holds a live broker link. Registered only when BOTH a broker
        # (the delivery rail) and a channel store (membership) are wired.
        if channel_store is not None:

            @app.post("/channels/{channel_id}/ping")
            async def ping_channel(
                channel_id: str, authorization: str | None = Header(default=None)
            ):
                # Auth: the same verifier the data path uses. The token's `sub`
                # is the caller's deviceId — the FleetOrDeviceVerifier accepts a
                # per-device EdDSA token (the device's own credential) here, the
                # same identity it registers its receive-link under.
                try:
                    claims = verifier.verify(_bearer(authorization))
                except AuthError:
                    return error_response(401, "unauthorized")
                sender = claims.get("sub")
                # Membership gate: a non-member (or a token with no usable sub)
                # may not ping the box (403). The sender need not be the owner —
                # any member may ping.
                if not sender or not channel_store.is_member(channel_id, sender):
                    return error_response(403, "forbidden", detail="not a channel member")

                frame = {
                    "type": "box.ping",
                    "channelId": channel_id,
                    "from": sender,
                    "ts": _dt.datetime.now(_dt.UTC).isoformat(),
                }
                # Fan out to every OTHER member: a member with a live link is
                # delivered to; one with no live link is listed offline (NOT an
                # error). The sender is excluded — you do not ping yourself.
                delivered: list[str] = []
                offline: list[str] = []
                for device_id in channel_store.members(channel_id)["deviceIds"]:
                    if device_id == sender:
                        continue
                    if await broker.send(device_id, frame):
                        delivered.append(device_id)
                    else:
                        offline.append(device_id)
                return JSONResponse(content={"delivered": delivered, "offline": offline})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/version")
    def version():
        return {"version": __version__}

    return app
