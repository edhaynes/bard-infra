"""Control API — FastAPI over the sim + sequencer + fault engine.

The console polls ``/state`` + ``/sections`` (+ the real Registry's ``/agents``) on a
short interval; mutations (``/bringup``, ``/bringdown``, ``/inject``, ``/resolve``) flip
state that the next tick reflects. A background loop (in ``server.py``) calls
``Orchestrator.step`` every ``REFINERY_TICK_SECONDS``; tests drive ``step`` directly.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from refinery.faults import FAULT_KINDS, FaultEngine
from refinery.model import default_topology_path, load_topology
from refinery.registry_client import RegistryReader
from refinery.selfheal import HealMode, SelfHealAgent
from refinery.sequencer import Sequencer
from refinery.sim import ElementState, RefinerySim

REFINERY_VERSION = "0.1.0"
HISTORY_LEN = 180  # samples kept per element for trend traces (strip-chart window)
PLANT_MINUTES_PER_TICK = 30  # time compression — a real controlled shutdown is ~1-2 days
#   (~89 ticks * 30 min = ~44h plant time, matching a real controlled bring-down)
_DEFAULT_CORS = "http://localhost:5175,http://127.0.0.1:5175"

# Purdue level per device type (for the Investigate network layout).
# sim state / unit-status -> cdn-sim SubgraphCanvas status palette
_SUB_STATUS = {
    "running": "ok",
    "starting": "degraded",
    "stopping": "degraded",
    "degraded": "degraded",
    "tripped": "failed",
    "down": "failed",
    "offline": "offline",
    "discovered": "isolated",
}

_PURDUE = {
    "sensor": 0,
    "gas": 0,
    "valve": 0,
    "mov": 0,
    "pump": 0,
    "plc": 1,
    "dcs": 1,
    "sis": 1,
    "rtu": 1,
    "switch": 2,
    "workstation": 2,
    "gateway": 3,
}


def _cors_origins() -> list[str]:
    return [o.strip() for o in os.environ.get("REFINERY_CORS_ORIGINS", _DEFAULT_CORS).split(",")]


class InjectBody(BaseModel):
    kind: str
    target: str


class ModeBody(BaseModel):
    mode: str


class AgentConfigBody(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None


class PromptBody(BaseModel):
    prompt: str


class Orchestrator:
    """Owns the runtime trio and exposes JSON-serialisable views + controls."""

    def __init__(self, *, seed: int = 0, registry: RegistryReader | None = None) -> None:
        self._seed = seed
        # Real bard-infra Registry reader (None = sim-only). Injectable for tests.
        self.registry = registry if registry is not None else RegistryReader.from_env()
        self.reset()

    def reset(self) -> None:
        self.sim = RefinerySim(load_topology(default_topology_path()), seed=self._seed)
        self.seq = Sequencer(self.sim)
        self.faults = FaultEngine(self.sim)
        self.agent = SelfHealAgent(self.faults)
        self.tick_count = 0
        self.history_ticks: deque[int] = deque(maxlen=HISTORY_LEN)
        self.history: dict[str, deque[float]] = {
            tag: deque(maxlen=HISTORY_LEN) for tag in self.sim.elements
        }

    def step(self) -> None:
        self.sim.tick()
        self.seq.tick()
        self.faults.tick()  # propagate cascades / recover, one step per tick
        self.agent.tick()
        self.tick_count += 1
        self.history_ticks.append(self.tick_count)
        for tag, rt in self.sim.elements.items():
            self.history[tag].append(round(rt.value, 2))

    # -- views -----------------------------------------------------------
    def state(self) -> dict:
        sig = self.sim.signals()
        seq = self.seq.status()
        # "off kilter" flags: alarms/trips that show up during an operation are the
        # transient anomalies Eddie wants surfaced (a controlled op should stay in band).
        flagged = sorted(set(sig["alarms"]) | set(sig["trips"]))
        return {
            "tick": self.tick_count,
            "plant_minutes_per_tick": PLANT_MINUTES_PER_TICK,
            "plant_minutes": self.tick_count * PLANT_MINUTES_PER_TICK,
            "signals": sig,
            "sequencer": seq,
            "incidents": [i.as_dict() for i in self.faults.incidents],
            "flagged": flagged,
            "agent": {
                "running": self.agent.running,
                "state": self.agent.state.value,
                "mode": self.agent.mode.value,
                "pending": len(self.agent.status()["pending"]),
            },
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

    def _registry_agents(self) -> tuple[str, dict[str, str]]:
        """(registry_state, {agentId: status}) from the real Registry, fail-soft."""
        if self.registry is None:
            return "disconnected", {}
        try:
            agents = self.registry.agents()
        except httpx.HTTPError:
            return "unreachable", {}
        return "connected", {a["agentId"]: a.get("status", "active") for a in agents}

    def discovery(self) -> dict:
        """Live self-discovery feed straight from the real bard-infra Registry."""
        state, agents = self._registry_agents()
        return {"registry": state, "count": len(agents), "agents": agents}

    def fleet(self) -> dict:
        """Every node joined with its real Registry liveness + network reachability."""
        state, agents = self._registry_agents()
        nodes: list[dict] = []
        failed = stale = unreachable = 0
        for s in self.sim.ref.sections:
            sw, gw = s.network["switch"], s.network["gateway"]
            sw_down = self.sim.elements[sw.tag].state is ElementState.DOWN
            gw_down = self.sim.elements[gw.tag].state is ElementState.DOWN
            for e in s.all_elements:
                reg = agents.get(e.agent_id, "absent")
                problem = None
                if sw_down and e.tag != sw.tag:
                    problem = f"section switch {sw.tag} down"
                elif gw_down and e.tag not in (sw.tag, gw.tag):
                    problem = f"gateway {gw.tag} down"
                elif reg == "stale":
                    problem = "heartbeat lost (Registry stale)"
                sim_state = self.sim.elements[e.tag].state.value
                if sim_state in ("tripped", "down") or reg == "stale":
                    failed += 1
                if reg == "stale":
                    stale += 1
                if problem is not None:
                    unreachable += 1
                nodes.append(
                    {
                        "tag": e.tag,
                        "type": e.type,
                        "section": e.section_id,
                        "unit": e.unit_id,
                        "sim_state": sim_state,
                        "registry": reg,
                        "reachable": problem is None,
                        "problem": problem,
                    }
                )
        return {
            "registry": state,
            "nodes": nodes,
            "summary": {
                "total": len(nodes),
                "failed": failed,
                "stale": stale,
                "unreachable": unreachable,
            },
        }

    def history_view(self, tags: list[str] | None = None) -> dict:
        """Recent value series for trend traces (all elements, or a requested subset)."""
        selected = tags if tags else list(self.sim.elements)
        return {
            "ticks": list(self.history_ticks),
            "series": {t: list(self.history[t]) for t in selected if t in self.history},
        }

    def graph(self) -> dict:
        """Unit dependency graph (feeds + utility + gate) for cascade analysis."""
        g = self.seq.graph
        units = self.sim.ref.units_by_id
        nodes = [
            {
                "id": uid,
                "name": units[uid].name,
                "kind": units[uid].kind,
                "section": units[uid].section_id,
                "status": self.sim.unit_status(uid),
            }
            for uid in g.nodes
        ]
        edges = [{"src": u, "dst": v, "kind": d.get("kind", "")} for u, v, d in g.edges(data=True)]
        return {"nodes": nodes, "edges": edges}

    def incident_subgraph(self, seq: int) -> dict:
        """The incident's blast-radius subgraph (cdn-sim SubgraphSlice shape).

        nodes = target + affected (resolved to type/name/status), edges = the real
        topology edges among them, cascade_order = the BFS reveal order.
        """
        inc = next((i for i in self.faults.incidents if i.seq == seq), None)
        if inc is None:
            raise KeyError(f"unknown incident {seq}")
        order: list[str] = []
        for nid in [inc.target, *inc.affected]:
            if nid not in order:
                order.append(nid)
        nodeset = set(order)
        nodes = [self._subnode(nid) for nid in order]
        seen: set[tuple[str, str]] = set()
        edges: list[dict] = []
        for e in (*self.graph()["edges"], *self.netgraph()["edges"]):
            src, dst = e["src"], e["dst"]
            if src in nodeset and dst in nodeset and (src, dst) not in seen:
                seen.add((src, dst))
                edges.append({"src": src, "dst": dst, "type": e.get("kind", "carries")})
        return {
            "nodes": nodes,
            "edges": edges,
            "target": inc.target,
            "cascade_order": order,
            "mode": inc.kind,
        }

    def _subnode(self, nid: str) -> dict:
        if nid in self.sim.elements:
            rt = self.sim.elements[nid]
            return {
                "id": nid,
                "node_type": rt.element.type,
                "name": nid,
                "status": _SUB_STATUS.get(rt.state.value, "failed"),
            }
        if nid in self.sim.ref.units_by_id:
            u = self.sim.ref.units_by_id[nid]
            return {
                "id": nid,
                "node_type": "unit",
                "name": u.name,
                "status": _SUB_STATUS.get(self.sim.unit_status(nid), "failed"),
            }
        return {"id": nid, "node_type": "section", "name": nid, "status": "isolated"}

    def netgraph(self) -> dict:
        """Device-level OT network topology (Purdue-wired) for the Investigate view.

        field devices -> unit controller (PLC/DCS) -> section switch -> gateway ->
        workstations, every section gateway -> a central PLANT core.
        """
        ref = self.sim.ref
        nodes: list[dict] = [
            {
                "id": "PLANT",
                "type": "plant",
                "section": "",
                "level": 4,
                "state": "running",
                "in_alarm": False,
                "in_trip": False,
                "value": None,
            }
        ]
        edges: list[dict] = []

        def add(tag: str) -> None:
            rt = self.sim.elements[tag]
            e = rt.element
            nodes.append(
                {
                    "id": e.tag,
                    "type": e.type,
                    "section": e.section_id,
                    "unit": e.unit_id,
                    "level": _PURDUE[e.type],
                    "state": rt.state.value,
                    "in_alarm": rt.in_alarm,
                    "in_trip": rt.in_trip,
                    "value": round(rt.value, 2),
                }
            )

        for s in ref.sections:
            sw, gw = s.network["switch"].tag, s.network["gateway"].tag
            for e in s.network.values():
                add(e.tag)
            edges.append({"src": sw, "dst": gw})
            for role in ("hmi", "ews"):
                edges.append({"src": gw, "dst": s.network[role].tag})
            edges.append({"src": gw, "dst": "PLANT"})
            for u in s.units:
                controller = next((e for e in u.elements if e.type in ("dcs", "plc")), None)
                ctl = controller.tag if controller else sw
                for e in u.elements:
                    add(e.tag)
                    if e.type in ("sensor", "gas", "valve", "mov", "pump"):
                        edges.append({"src": e.tag, "dst": ctl})
                    else:  # plc / dcs / sis / rtu -> switch
                        edges.append({"src": e.tag, "dst": sw})
        return {"nodes": nodes, "edges": edges}


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

    @app.get("/history")
    def history(tags: str | None = None) -> dict:
        taglist = [t for t in tags.split(",") if t] if tags else None
        return orch.history_view(taglist)

    @app.get("/graph")
    def graph() -> dict:
        return orch.graph()

    @app.get("/netgraph")
    def netgraph() -> dict:
        return orch.netgraph()

    @app.get("/incident_subgraph/{seq}")
    def incident_subgraph(seq: int) -> dict:
        try:
            return orch.incident_subgraph(seq)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/discovery")
    def discovery() -> dict:
        return orch.discovery()

    @app.get("/fleet")
    def fleet() -> dict:
        return orch.fleet()

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

    @app.get("/agent/status")
    def agent_status() -> dict:
        return orch.agent.status()

    @app.post("/agent/start")
    def agent_start() -> dict:
        orch.agent.start()
        return orch.agent.status()

    @app.post("/agent/stop")
    def agent_stop() -> dict:
        orch.agent.stop()
        return orch.agent.status()

    @app.get("/agent/config")
    def agent_config() -> dict:
        return orch.agent.get_config()

    @app.post("/agent/config")
    def agent_set_config(body: AgentConfigBody) -> dict:
        orch.agent.set_config(body.provider, body.model, body.api_key, body.base_url)
        return orch.agent.get_config()

    @app.get("/agent/prompt")
    def agent_prompt() -> dict:
        return {"prompt": orch.agent.system_prompt}

    @app.post("/agent/prompt")
    def agent_set_prompt(body: PromptBody) -> dict:
        orch.agent.set_prompt(body.prompt)
        return {"prompt": orch.agent.system_prompt}

    @app.post("/agent/prompt/polish")
    def agent_polish_prompt() -> dict:
        return {"prompt": orch.agent.polish_prompt()}

    @app.post("/agent/mode")
    def agent_mode(body: ModeBody) -> dict:
        try:
            orch.agent.set_mode(HealMode(body.mode))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown mode '{body.mode}'") from exc
        return orch.agent.status()

    @app.post("/agent/approve/{event_id}")
    def agent_approve(event_id: int) -> dict:
        try:
            return orch.agent.approve(event_id).as_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip('"')) from exc

    @app.post("/agent/reject/{event_id}")
    def agent_reject(event_id: int) -> dict:
        try:
            return orch.agent.reject(event_id).as_dict()
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

    # Optionally serve the built console as same-origin static files (one Cloud Run
    # service hosts API + dashboard). Mounted last so API routes take precedence.
    dist = os.environ.get("REFINERY_CONSOLE_DIST")
    if dist and Path(dist).is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="console")

    return app
