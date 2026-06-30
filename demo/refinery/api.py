"""Control API — FastAPI over the sim + sequencer + fault engine.

The console polls ``/state`` + ``/sections`` (+ the real Registry's ``/agents``) on a
short interval; mutations (``/bringup``, ``/bringdown``, ``/inject``, ``/resolve``) flip
state that the next tick reflects. A background loop (in ``server.py``) calls
``Orchestrator.step`` every ``REFINERY_TICK_SECONDS``; tests drive ``step`` directly.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from refinery.faults import FAULT_KINDS, FaultEngine
from refinery.model import default_topology_path, load_topology
from refinery.sequencer import Sequencer
from refinery.sim import RefinerySim

REFINERY_VERSION = "0.1.0"
_DEFAULT_CORS = "http://localhost:5175,http://127.0.0.1:5175"


def _cors_origins() -> list[str]:
    return [o.strip() for o in os.environ.get("REFINERY_CORS_ORIGINS", _DEFAULT_CORS).split(",")]


class InjectBody(BaseModel):
    kind: str
    target: str


class Orchestrator:
    """Owns the runtime trio and exposes JSON-serialisable views + controls."""

    def __init__(self, *, seed: int = 0) -> None:
        self._seed = seed
        self.reset()

    def reset(self) -> None:
        self.sim = RefinerySim(load_topology(default_topology_path()), seed=self._seed)
        self.seq = Sequencer(self.sim)
        self.faults = FaultEngine(self.sim)
        self.tick_count = 0

    def step(self) -> None:
        self.sim.tick()
        self.seq.tick()
        self.tick_count += 1

    # -- views -----------------------------------------------------------
    def state(self) -> dict:
        return {
            "tick": self.tick_count,
            "signals": self.sim.signals(),
            "sequencer": self.seq.status(),
            "incidents": [i.as_dict() for i in self.faults.incidents],
        }

    def _element_view(self, tag: str) -> dict:
        rt = self.sim.elements[tag]
        e = rt.element
        return {
            "tag": e.tag,
            "agent_id": e.agent_id,
            "type": e.type,
            "signal": e.signal,
            "unit": e.unit,
            "section": e.section_id,
            "process_unit": e.unit_id,
            "value": round(rt.value, 2),
            "setpoint": e.setpoint,
            "state": rt.state.value,
            "in_alarm": rt.in_alarm,
            "in_trip": rt.in_trip,
        }

    def elements(self) -> list[dict]:
        return [self._element_view(t) for t in self.sim.elements]

    def sections(self) -> list[dict]:
        out = []
        for s in self.sim.ref.sections:
            units = [
                {
                    "id": u.id,
                    "name": u.name,
                    "kind": u.kind,
                    "status": self.sim.unit_status(u.id),
                    "elements": [self._element_view(e.tag) for e in u.elements],
                }
                for u in s.units
            ]
            out.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "bringup_order": s.bringup_order,
                    "network": [self._element_view(e.tag) for e in s.network.values()],
                    "units": units,
                }
            )
        return out

    def fault_kinds(self) -> dict:
        return FAULT_KINDS


def create_app(orch: Orchestrator) -> FastAPI:
    app = FastAPI(title="Refinery Orchestrator", version=REFINERY_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": REFINERY_VERSION}

    @app.get("/version")
    def version() -> dict:
        return {"version": REFINERY_VERSION}

    @app.get("/state")
    def state() -> dict:
        return orch.state()

    @app.get("/sections")
    def sections() -> list[dict]:
        return orch.sections()

    @app.get("/elements")
    def elements() -> list[dict]:
        return orch.elements()

    @app.get("/faults")
    def faults() -> dict:
        return orch.fault_kinds()

    @app.post("/bringup")
    def bringup() -> dict:
        orch.seq.start_bringup()
        return orch.seq.status()

    @app.post("/bringdown")
    def bringdown() -> dict:
        orch.seq.start_bringdown()
        return orch.seq.status()

    @app.post("/inject")
    def inject(body: InjectBody) -> dict:
        try:
            return orch.faults.inject(body.kind, body.target).as_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip('"')) from exc

    @app.post("/resolve/{seq}")
    def resolve(seq: int) -> dict:
        try:
            return orch.faults.resolve(seq).as_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip('"')) from exc

    @app.post("/reset")
    def reset() -> dict:
        orch.reset()
        return {"status": "reset"}

    @app.post("/step")
    def step() -> dict:
        orch.step()
        return {"tick": orch.tick_count}

    return app
