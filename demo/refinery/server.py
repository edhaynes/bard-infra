"""Orchestrator entrypoint: ``uvicorn refinery.server:app``.

Runs a background loop that advances the sim one tick every REFINERY_TICK_SECONDS so
the plant telemetry, bring-up/down, and fault cascades evolve in real time. Excluded
from coverage (the runtime wiring is exercised by the local-run verification, not units).
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from refinery.api import Orchestrator, create_app

orch = Orchestrator()
app = create_app(orch)


@app.on_event("startup")
async def _start_ticker() -> None:
    interval = float(os.environ.get("REFINERY_TICK_SECONDS", "1.0"))

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            orch.step()

    app.state.ticker = asyncio.create_task(_loop())


@app.on_event("shutdown")
async def _stop_ticker() -> None:
    task = getattr(app.state, "ticker", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
