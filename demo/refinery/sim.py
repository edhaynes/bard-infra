"""Refinery runtime — element state machine, deterministic telemetry, signals.

Wraps the static :class:`~refinery.model.Refinery` topology with live runtime: each
element has a state (offline/discovered/starting/running/tripped/down) and a telemetry
value advanced each ``tick``. Telemetry is deterministic given a seeded RNG so tests are
reproducible. Sequencing (bring-up/down order, interlocks) and fault injection live in
:mod:`refinery.sequencer` (Sprint 4); this module is the substrate they drive.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from refinery.model import Element, Refinery, default_topology_path, load_topology

RAMP_TICKS = 5  # ticks for a starting element to ramp to its setpoint
NOISE_RUNNING = 0.15  # fraction of band used as running jitter
NOISE_STARTING = 0.05


class ElementState(str, Enum):
    OFFLINE = "offline"  # not powered / not registered
    DISCOVERED = "discovered"  # registered into the Registry, unit idle
    STARTING = "starting"  # unit bring-up in progress
    RUNNING = "running"  # normal operation, telemetry near setpoint
    TRIPPED = "tripped"  # SIS / interlock took it to a safe state
    DOWN = "down"  # failed / unreachable (heartbeat lost)


LIVE_STATES = frozenset({ElementState.RUNNING, ElementState.STARTING, ElementState.TRIPPED})


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class ElementRuntime:
    """Live state + telemetry for one element."""

    element: Element
    state: ElementState = ElementState.OFFLINE
    value: float = 0.0
    ramp: float = 0.0

    @property
    def is_sis(self) -> bool:
        return self.element.type == "sis"

    @property
    def target(self) -> float:
        e = self.element
        if e.setpoint is not None:
            return float(e.setpoint)
        lo, hi = e.normal
        return (lo + hi) / 2

    def _running_value(self, rng: random.Random) -> float:
        if self.is_sis:
            return 0.0
        lo, hi = self.element.normal
        noise = (rng.random() - 0.5) * (hi - lo) * NOISE_RUNNING
        return _clamp(self.target + noise, lo, hi)

    def _starting_value(self, rng: random.Random) -> float:
        if self.is_sis:
            return 0.0
        lo, hi = self.element.normal
        noise = (rng.random() - 0.5) * (hi - lo) * NOISE_STARTING
        return _clamp(self.target * self.ramp + noise, lo, hi)

    def tick(self, rng: random.Random) -> None:
        """Advance telemetry one step according to the current state."""
        if self.state is ElementState.RUNNING:
            self.value = self._running_value(rng)
        elif self.state is ElementState.STARTING:
            self.ramp = min(1.0, self.ramp + 1.0 / RAMP_TICKS)
            self.value = self._starting_value(rng)
        elif self.state is ElementState.TRIPPED:
            self.value = 1.0 if self.is_sis else 0.0
        else:  # OFFLINE, DISCOVERED, DOWN — no live reading
            self.value = 0.0

    @property
    def ready(self) -> bool:
        """True once a STARTING element has finished ramping (sequencer promotes it)."""
        return self.ramp >= 1.0

    @property
    def in_alarm(self) -> bool:
        if self.state not in LIVE_STATES:
            return False
        e = self.element
        high = e.alarm_high is not None and self.value >= e.alarm_high
        low = e.alarm_low is not None and self.value <= e.alarm_low
        return bool(high or low)

    @property
    def in_trip(self) -> bool:
        if self.state not in LIVE_STATES:
            return False
        e = self.element
        high = e.trip_high is not None and self.value >= e.trip_high
        low = e.trip_low is not None and self.value <= e.trip_low
        return bool(high or low)


class RefinerySim:
    """Runtime over a :class:`Refinery` topology."""

    def __init__(self, ref: Refinery, *, seed: int = 0) -> None:
        self.ref = ref
        self.rng = random.Random(seed)
        self.elements: dict[str, ElementRuntime] = {
            e.tag: ElementRuntime(e) for e in ref.all_elements
        }

    @classmethod
    def from_default(cls, *, seed: int = 0) -> RefinerySim:
        return cls(load_topology(default_topology_path()), seed=seed)

    # -- mutation --------------------------------------------------------
    def tick(self) -> None:
        for rt in self.elements.values():
            rt.tick(self.rng)

    def runtime(self, tag: str) -> ElementRuntime:
        try:
            return self.elements[tag]
        except KeyError as exc:
            raise KeyError(f"unknown element tag '{tag}'") from exc

    def set_element_state(self, tag: str, state: ElementState) -> None:
        rt = self.runtime(tag)
        if state is ElementState.STARTING:
            rt.ramp = 0.0
        rt.state = state

    def set_unit_state(self, unit_id: str, state: ElementState) -> None:
        """Set every process element of a unit to ``state``."""
        unit = self.ref.units_by_id.get(unit_id)
        if unit is None:
            raise KeyError(f"unknown unit '{unit_id}'")
        for e in unit.elements:
            self.set_element_state(e.tag, state)

    def set_section_network_state(self, section_id: str, state: ElementState) -> None:
        """Set a section's shared network gear (switch/gateway/hmi/ews)."""
        section = self.ref.sections_by_id.get(section_id)
        if section is None:
            raise KeyError(f"unknown section '{section_id}'")
        for e in section.network.values():
            self.set_element_state(e.tag, state)

    def discover_all(self) -> None:
        """Mark every element DISCOVERED (post self-registration, plant idle)."""
        for rt in self.elements.values():
            rt.state = ElementState.DISCOVERED
            rt.ramp = 0.0

    # -- read ------------------------------------------------------------
    def unit_status(self, unit_id: str) -> str:
        unit = self.ref.units_by_id[unit_id]
        states = [self.elements[e.tag].state for e in unit.elements]
        return _rollup(states)

    def signals(self) -> dict:
        """Plant + per-section rollup for the console KPI/section views."""
        by_state = Counter(rt.state.value for rt in self.elements.values())
        alarms = sorted(t for t, rt in self.elements.items() if rt.in_alarm)
        trips = sorted(t for t, rt in self.elements.items() if rt.in_trip)

        sections = {}
        for s in self.ref.sections:
            tags = [e.tag for e in s.all_elements]
            states = [self.elements[t].state for t in tags]
            running = sum(1 for st in states if st is ElementState.RUNNING)
            sec_alarms = sum(1 for t in tags if self.elements[t].in_alarm)
            sections[s.id] = {
                "name": s.name,
                "status": _rollup(states),
                "running": running,
                "total": len(tags),
                "alarms": sec_alarms,
            }

        units_total = len(self.ref.units_by_id)
        units_running = sum(1 for uid in self.ref.units_by_id if self.unit_status(uid) == "running")
        return {
            "elements_total": len(self.elements),
            "by_state": dict(by_state),
            "alarms": alarms,
            "trips": trips,
            "sections": sections,
            "units_total": units_total,
            "units_running": units_running,
        }


def _rollup(states: list[ElementState]) -> str:
    """Worst-wins status rollup for a unit/section."""
    if not states:
        return "offline"
    sset = set(states)
    if ElementState.DOWN in sset:
        return "down"
    if ElementState.TRIPPED in sset:
        return "tripped"
    if ElementState.STARTING in sset:
        return "starting"
    if sset == {ElementState.RUNNING}:
        return "running"
    if ElementState.RUNNING in sset:
        return "partial"
    if sset == {ElementState.DISCOVERED}:
        return "discovered"
    return "offline"
