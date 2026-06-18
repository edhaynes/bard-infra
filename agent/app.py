"""FastAPI app for the Agent (agent.openapi.yaml).

Validates the JWT in ``Request.metadata.authToken`` (the same token the Router
forwarded), rejects voice with 501, and runs the injected engine. Optional
``heartbeat`` (feature #54) and ``broker`` (feature #59) coroutine factories
are started as background tasks on app startup and cancelled cleanly on
shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent.engine import InferenceEngine, InferenceError
from common.auth import AuthError, TokenVerifier
from common.errors import error_response
from common.metrics import AppMetrics, instrument, make_inference_counter
from common.protocol import Request
from common.version import __version__


def create_app(
    engine: InferenceEngine,
    verifier: TokenVerifier,
    *,
    heartbeat: Callable[[], Coroutine[Any, Any, None]] | None = None,
    broker: Callable[[], Coroutine[Any, Any, None]] | None = None,
    metrics: AppMetrics | None = None,
    backend_name: str = "unknown",
) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        factories = [f for f in (heartbeat, broker) if f is not None]
        tasks = [asyncio.create_task(factory()) for factory in factories]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Bard Agent", version=__version__, lifespan=_lifespan)
    metrics = metrics or AppMetrics("agent")
    instrument(app, metrics)
    inference_counter = make_inference_counter(metrics)

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_request, _exc):
        return error_response(400, "bad_request")

    @app.post("/infer")
    def infer(request: Request):
        try:
            verifier.verify(request.metadata.authToken)
        except AuthError:
            return error_response(401, "unauthorized")
        if request.type == "voice":
            return error_response(501, "unsupported_type", detail="voice not supported in MVP")
        try:
            response = engine.infer(request)
        except InferenceError as exc:
            inference_counter.labels(backend=backend_name, outcome="error").inc()
            return error_response(502, "inference_failed", retry=True, detail=str(exc))
        inference_counter.labels(backend=backend_name, outcome="ok").inc()
        return JSONResponse(content=response.model_dump(exclude_none=True))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/version")
    def version():
        return {"version": __version__}

    return app
