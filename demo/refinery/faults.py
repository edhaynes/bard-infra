"""Fault injection + cascade propagation — the failure-handling pillar.

Inject a fault on a target; it trips/downs elements and **cascades through the same
dependency graph the sequencer uses** (loss of a utility trips its consumers, a tripped
unit trips everything downstream that was running, a switch failure blinds its section).
Resolve restores the affected items. Element-offline mirrors the real Registry-stale
signal from the projector (a lost heartbeat = a dark element).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from refinery.sequencer import dependency_graph
from refinery.sim import ElementState, RefinerySim

# Injectable fault kinds, with the target each expects (for the console menu).
FAULT_KINDS: dict[str, dict[str, str]] = {
    "unit_trip": {"label": "Unit SIS trip", "target": "unit"},
    "loss_of_utility": {"label": "Loss of utility (steam/H2/...)", "target": "unit"},
    "gas_release": {"label": "Gas release → SIS trip", "target": "unit"},
    "switch_down": {"label": "Switch failure (section blind)", "target": "section"},
    "pump_vibration": {"label": "Pump high-vibration trip", "target": "pump"},
    "element_offline": {"label": "Element offline (heartbeat lost)", "target": "element"},
}

_UNIT_KINDS = {"unit_trip", "loss_of_utility", "gas_release"}


@dataclass
class Incident:
    seq: int
    kind: str
    target: str
    description: str
    affected: list[str] = field(default_factory=list)
    resolved: bool = False

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "target": self.target,
            "description": self.description,
            "affected": self.affected,
            "resolved": self.resolved,
        }


class FaultEngine:
    """Injects faults into a sim and propagates the cascade through the graph."""

    def __init__(self, sim: RefinerySim) -> None:
        self.sim = sim
        self.g = dependency_graph(sim.ref)
        self.incidents: list[Incident] = []
        self._seq = 0

    # -- injection -------------------------------------------------------
    def inject(self, kind: str, target: str) -> Incident:
        if kind in _UNIT_KINDS:
            affected, desc = self._trip_unit(target, kind)
        elif kind == "switch_down":
            affected, desc = self._switch_down(target)
        elif kind == "pump_vibration":
            affected, desc = self._pump_trip(target)
        elif kind == "element_offline":
            affected, desc = self._element_offline(target)
        else:
            raise ValueError(f"unknown fault kind '{kind}'")
        self._seq += 1
        inc = Incident(self._seq, kind, target, desc, affected)
        self.incidents.append(inc)
        return inc

    def _cascade(self, unit_id: str, affected: list[str]) -> None:
        """Trip every still-running downstream dependent, in propagation (BFS) order.

        BFS from the trip origin so ``affected`` reads as the order the failure spread
        outward layer by layer — the console animates the node-walk along this order.
        """
        for dep in nx.bfs_tree(self.g, unit_id):
            if dep == unit_id:
                continue
            if self.sim.unit_status(dep) == "running":
                self.sim.set_unit_state(dep, ElementState.TRIPPED)
                affected.append(dep)

    def _trip_unit(self, unit_id: str, kind: str) -> tuple[list[str], str]:
        if unit_id not in self.sim.ref.units_by_id:
            raise KeyError(f"unknown unit '{unit_id}'")
        self.sim.set_unit_state(unit_id, ElementState.TRIPPED)
        affected = [unit_id]
        self._cascade(unit_id, affected)
        name = self.sim.ref.units_by_id[unit_id].name
        reason = {
            "unit_trip": "SIS trip",
            "loss_of_utility": "loss of utility",
            "gas_release": "gas release → SIS trip",
        }[kind]
        return affected, f"{name} ({unit_id}): {reason}; {len(affected) - 1} downstream tripped"

    def _switch_down(self, section_id: str) -> tuple[list[str], str]:
        section = self.sim.ref.sections_by_id.get(section_id)
        if section is None:
            raise KeyError(f"unknown section '{section_id}'")
        switch_tag = section.network["switch"].tag
        self.sim.set_element_state(switch_tag, ElementState.DOWN)
        affected = [switch_tag]
        for u in section.units:
            self.sim.set_unit_state(u.id, ElementState.DOWN)
            affected.append(u.id)
        return affected, f"switch {switch_tag} failed: section {section_id} blind"

    def _pump_trip(self, tag: str) -> tuple[list[str], str]:
        rt = self.sim.runtime(tag)
        if rt.element.type != "pump":
            raise ValueError(f"element '{tag}' is not a pump")
        unit_id = rt.element.unit_id
        affected, _ = self._trip_unit(unit_id, "unit_trip")
        self.sim.set_element_state(tag, ElementState.DOWN)  # pump itself dark
        affected.insert(0, tag)
        return affected, f"pump {tag} high vibration trip; unit {unit_id} down"

    def _element_offline(self, tag: str) -> tuple[list[str], str]:
        self.sim.set_element_state(tag, ElementState.DOWN)
        return [tag], f"element {tag} offline (heartbeat lost / Registry stale)"

    # -- resolution ------------------------------------------------------
    def resolve(self, seq: int) -> Incident:
        inc = next((i for i in self.incidents if i.seq == seq), None)
        if inc is None:
            raise KeyError(f"unknown incident seq {seq}")
        for item in inc.affected:
            if item in self.sim.ref.units_by_id:
                self.sim.set_unit_state(item, ElementState.RUNNING)
            else:
                self.sim.set_element_state(item, ElementState.RUNNING)
        inc.resolved = True
        return inc

    def open_incidents(self) -> list[Incident]:
        return [i for i in self.incidents if not i.resolved]
