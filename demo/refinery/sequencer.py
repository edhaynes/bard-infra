"""Bring-up / bring-down sequencer — the two critical refinery operations.

Computes a dependency-correct unit order (topological sort over the feeds + utility +
interlock-gate edges, section bring-up order as tiebreak) so utilities/flare/steam/H2
come up first and conversion last. Bring-up is tick-driven and cascading: each tick,
every unit whose prerequisites are RUNNING starts ramping, so the plant lights up in
dependency layers. Bring-down runs the reverse: a unit shuts only once everything it
feeds (or gates) is already down, utilities last (safe depressurization).
"""

from __future__ import annotations

from enum import Enum

import networkx as nx

from refinery.model import Refinery
from refinery.sim import ElementState, RefinerySim


class SeqMode(str, Enum):
    IDLE = "idle"
    BRINGING_UP = "bringing_up"
    BRINGING_DOWN = "bringing_down"


# Unit states that count as "shut" for bring-down dependency checks.
_DOWN_STATES = {"offline", "discovered"}


def dependency_graph(ref: Refinery) -> nx.DiGraph:
    """Process+utility dependency graph plus interlock-gate edges.

    Shared by the sequencer (ordering) and the fault engine (cascade). An edge
    ``a -> b`` means *b depends on a* — a's loss can cascade to b.
    """
    g = ref.graph.copy()
    for u in ref.units_by_id.values():
        for gate in u.gates:
            for req in ref.gate_requirements(gate):
                if req != u.id:
                    g.add_edge(req, u.id, kind="gate")
    return g


class Sequencer:
    """Drives ordered, interlock-gated bring-up and bring-down over a sim."""

    def __init__(self, sim: RefinerySim) -> None:
        self.sim = sim
        self.mode = SeqMode.IDLE
        self._g = dependency_graph(sim.ref)
        self.order = self._compute_order()
        self.blocked: tuple[str, str] | None = None

    @property
    def graph(self) -> nx.DiGraph:
        """The combined dependency graph (feeds + utility + interlock-gate edges)."""
        return self._g

    # -- ordering --------------------------------------------------------
    def _compute_order(self) -> list[str]:
        ref = self.sim.ref
        section_order = {
            uid: ref.sections_by_id[u.section_id].bringup_order
            for uid, u in ref.units_by_id.items()
        }
        return list(
            nx.lexicographical_topological_sort(self._g, key=lambda uid: (section_order[uid], uid))
        )

    def prereqs_met(self, unit_id: str) -> bool:
        return all(self.sim.unit_status(p) == "running" for p in self._g.predecessors(unit_id))

    def _unit_ready(self, unit_id: str) -> bool:
        """All of a starting unit's elements have finished ramping up."""
        unit = self.sim.ref.units_by_id[unit_id]
        return all(self.sim.elements[e.tag].ready for e in unit.elements)

    def _unit_stopped(self, unit_id: str) -> bool:
        """All of a stopping unit's elements have finished cooling down."""
        unit = self.sim.ref.units_by_id[unit_id]
        return all(self.sim.elements[e.tag].stopped for e in unit.elements)

    # -- control ---------------------------------------------------------
    def start_bringup(self) -> None:
        self.mode = SeqMode.BRINGING_UP
        self.blocked = None
        self.sim.discover_all()
        for s in self.sim.ref.sections:
            self.sim.set_section_network_state(s.id, ElementState.RUNNING)

    def start_bringdown(self) -> None:
        self.mode = SeqMode.BRINGING_DOWN
        self.blocked = None

    def tick(self) -> None:
        """Advance the active operation one step (call after sim.tick())."""
        if self.mode is SeqMode.BRINGING_UP:
            self._advance_up()
        elif self.mode is SeqMode.BRINGING_DOWN:
            self._advance_down()

    def _advance_up(self) -> None:
        # promote ramped starting units to running
        for uid in self.order:
            if self.sim.unit_status(uid) == "starting" and self._unit_ready(uid):
                self.sim.set_unit_state(uid, ElementState.RUNNING)
        # start every newly-eligible unit (cascading by dependency layer)
        self.blocked = None
        for uid in self.order:
            if self.sim.unit_status(uid) in _DOWN_STATES:
                if self.prereqs_met(uid):
                    self.sim.set_unit_state(uid, ElementState.STARTING)
                else:
                    self.blocked = (uid, self._block_reason(uid))
        if all(self.sim.unit_status(uid) == "running" for uid in self.order):
            self.mode = SeqMode.IDLE

    def _advance_down(self) -> None:
        # 1. units that have finished cooling drop fully offline
        for uid in self.order:
            if self.sim.unit_status(uid) == "stopping" and self._unit_stopped(uid):
                self.sim.set_unit_state(uid, ElementState.OFFLINE)
        # 2. start the controlled cool-down of any unit whose downstream (everything it
        #    feeds/gates) is already fully offline — leaf-first, ramped, never a cliff.
        snapshot = {uid: self.sim.unit_status(uid) for uid in self.order}
        for uid in self.order:
            deps_down = all(snapshot[s] in _DOWN_STATES for s in self._g.successors(uid))
            if snapshot[uid] == "running" and deps_down:
                self.sim.set_unit_state(uid, ElementState.STOPPING)
        if all(self.sim.unit_status(uid) in _DOWN_STATES for uid in self.order):
            for s in self.sim.ref.sections:
                self.sim.set_section_network_state(s.id, ElementState.OFFLINE)
            self.mode = SeqMode.IDLE

    def _block_reason(self, unit_id: str) -> str:
        waiting = [p for p in self._g.predecessors(unit_id) if self.sim.unit_status(p) != "running"]
        return f"waiting on {', '.join(sorted(set(waiting)))}"

    def status(self) -> dict:
        running = sum(1 for uid in self.order if self.sim.unit_status(uid) == "running")
        return {
            "mode": self.mode.value,
            "units_running": running,
            "units_total": len(self.order),
            "blocked": (
                {"unit": self.blocked[0], "reason": self.blocked[1]} if self.blocked else None
            ),
        }
