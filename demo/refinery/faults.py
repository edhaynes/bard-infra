"""Fault injection with GRADUAL cascade propagation + gradual recovery.

A fault doesn't take the whole plant down in one instant — it happens at a point and
then **propagates through the dependency graph over time** (one step per tick), and
recovery rolls back the same way. Each incident carries an ordered ``plan`` (origin
first, BFS outward); :meth:`FaultEngine.tick` applies the next step each tick while
the fault spreads, then restores in reverse once a resolve is requested.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from refinery.sequencer import dependency_graph
from refinery.sim import ElementState, RefinerySim

FAULT_KINDS: dict[str, dict[str, str]] = {
    "unit_trip": {"label": "Unit SIS trip", "target": "unit"},
    "loss_of_utility": {"label": "Loss of utility (steam/H2/...)", "target": "unit"},
    "gas_release": {"label": "Gas release → SIS trip", "target": "unit"},
    "switch_down": {"label": "Switch failure (section blind)", "target": "section"},
    "pump_vibration": {"label": "Pump high-vibration trip", "target": "pump"},
    "element_offline": {"label": "Element offline (heartbeat lost)", "target": "element"},
}

_UNIT_KINDS = {"unit_trip", "loss_of_utility", "gas_release"}
_REASON = {
    "unit_trip": "SIS trip",
    "loss_of_utility": "loss of utility",
    "gas_release": "gas release → SIS trip",
}


@dataclass
class Incident:
    """An incident whose impact propagates (and recovers) gradually over ticks."""

    seq: int
    kind: str
    target: str
    description: str
    plan: list[tuple[str, str]] = field(default_factory=list)  # (id, down_state) in spread order
    applied: int = 0  # how many plan steps have gone down so far
    resolving: bool = False
    restored: int = 0  # how many have been restored (reverse order)
    resolved: bool = False

    @property
    def affected(self) -> list[str]:
        return [p[0] for p in self.plan]

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "target": self.target,
            "description": self.description,
            "affected": self.affected,
            "applied": self.applied,
            "resolving": self.resolving,
            "resolved": self.resolved,
        }


class FaultEngine:
    """Injects faults and propagates the cascade (and recovery) one step per tick."""

    def __init__(self, sim: RefinerySim) -> None:
        self.sim = sim
        self.g = dependency_graph(sim.ref)
        self.incidents: list[Incident] = []
        self._seq = 0

    # -- injection -------------------------------------------------------
    def inject(self, kind: str, target: str) -> Incident:
        plan, desc = self._plan(kind, target)
        self._seq += 1
        inc = Incident(self._seq, kind, target, desc, plan)
        self._apply(plan[0])  # the origin fails immediately; the rest spreads over ticks
        inc.applied = 1
        self.incidents.append(inc)
        return inc

    def _plan(self, kind: str, target: str) -> tuple[list[tuple[str, str]], str]:
        if kind in _UNIT_KINDS:
            return self._plan_unit(target, kind)
        if kind == "switch_down":
            return self._plan_switch(target)
        if kind == "pump_vibration":
            return self._plan_pump(target)
        if kind == "element_offline":
            return self._plan_element(target)
        raise ValueError(f"unknown fault kind '{kind}'")

    def _cascade_plan(self, unit_id: str) -> list[tuple[str, str]]:
        """BFS-ordered downstream units that would trip (computed at inject time)."""
        out: list[tuple[str, str]] = []
        for dep in nx.bfs_tree(self.g, unit_id):
            if dep != unit_id and self.sim.unit_status(dep) == "running":
                out.append((dep, "tripped"))
        return out

    def _plan_unit(self, unit_id: str, kind: str) -> tuple[list[tuple[str, str]], str]:
        if unit_id not in self.sim.ref.units_by_id:
            raise KeyError(f"unknown unit '{unit_id}'")
        plan = [(unit_id, "tripped"), *self._cascade_plan(unit_id)]
        name = self.sim.ref.units_by_id[unit_id].name
        return plan, f"{name} ({unit_id}): {_REASON[kind]}; {len(plan) - 1} downstream"

    def _plan_switch(self, section_id: str) -> tuple[list[tuple[str, str]], str]:
        section = self.sim.ref.sections_by_id.get(section_id)
        if section is None:
            raise KeyError(f"unknown section '{section_id}'")
        switch_tag = section.network["switch"].tag
        plan = [(switch_tag, "down"), *((u.id, "down") for u in section.units)]
        return plan, f"switch {switch_tag} failed: section {section_id} blind"

    def _plan_pump(self, tag: str) -> tuple[list[tuple[str, str]], str]:
        rt = self.sim.runtime(tag)
        if rt.element.type != "pump":
            raise ValueError(f"element '{tag}' is not a pump")
        unit_id = rt.element.unit_id
        # the pump dies (origin) — its unit reads "down" via the worst-wins rollup — and
        # the loss of that unit cascades downstream.
        plan = [(tag, "down"), *self._cascade_plan(unit_id)]
        return plan, f"pump {tag} high vibration; unit {unit_id} down"

    def _plan_element(self, tag: str) -> tuple[list[tuple[str, str]], str]:
        self.sim.runtime(tag)  # validates the tag exists
        return [(tag, "down")], f"element {tag} offline (heartbeat lost / Registry stale)"

    # -- propagation -----------------------------------------------------
    def _apply(self, item: tuple[str, str]) -> None:
        node, down = item
        if node in self.sim.ref.units_by_id:
            self.sim.set_unit_state(
                node, ElementState.DOWN if down == "down" else ElementState.TRIPPED
            )
        else:
            self.sim.set_element_state(node, ElementState.DOWN)

    def _restore(self, item: tuple[str, str]) -> None:
        node = item[0]
        if node in self.sim.ref.units_by_id:
            self.sim.set_unit_state(node, ElementState.RUNNING)
        else:
            self.sim.set_element_state(node, ElementState.RUNNING)

    def tick(self) -> None:
        """Advance every active incident one step — cascade outward, or recover back."""
        for inc in self.incidents:
            if inc.resolved:
                continue
            if inc.resolving:
                # restore one step per tick, reverse order; resolved (and skipped) once
                # the whole applied prefix is back — so this only runs while < applied.
                self._restore(inc.plan[inc.applied - 1 - inc.restored])
                inc.restored += 1
                if inc.restored >= inc.applied:
                    inc.resolved = True
            elif inc.applied < len(inc.plan):
                self._apply(inc.plan[inc.applied])
                inc.applied += 1

    # -- resolution ------------------------------------------------------
    def resolve(self, seq: int) -> Incident:
        """Request recovery — it rolls back gradually over ticks (reverse order)."""
        inc = next((i for i in self.incidents if i.seq == seq), None)
        if inc is None:
            raise KeyError(f"unknown incident seq {seq}")
        if not inc.resolved and not inc.resolving:
            inc.resolving = True
            inc.restored = 0
        return inc

    def open_incidents(self) -> list[Incident]:
        return [i for i in self.incidents if not i.resolved]
