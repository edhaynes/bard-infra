"""Self-healing agent — the autorepair "whole point" (deterministic, no LLM).

Adapts cdn-sim's NOC-agent skeleton (detect → diagnose → remediate) but closes the loop
and makes it deterministic: on a trip/offline incident it picks a remediation by fault
kind, then **auto-applies safe, reversible actions** (failover, twin promotion, reroute)
after a short delay (so the operator sees the cascade first) and **holds dangerous ones**
(SIS/gas trips) for human approval. The pitch contrast with cdn-sim: cdn-sim proposes and
waits; the refinery self-heals, with the human gate reserved for the dangerous actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from refinery.faults import FaultEngine

HEAL_DELAY_TICKS = 4  # let the cascade display before an auto-heal fires

# Safe, reversible faults the agent may auto-heal; SIS/gas trips need a human.
_AUTO_SAFE = frozenset({"element_offline", "switch_down", "loss_of_utility", "pump_vibration"})

REMEDIATION = {
    "element_offline": "promote digital twin — serve last-known state from a replica",
    "switch_down": "reroute the section through its redundant gateway",
    "loss_of_utility": "fail over to the backup utility feed",
    "pump_vibration": "isolate pump, start the standby",
    "unit_trip": "reset interlock and restart the unit",
    "gas_release": "purge, confirm gas cleared, then restart",
}


class AgentState(str, Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    REMEDIATING = "remediating"


class HealMode(str, Enum):
    AUTO = "auto"  # auto-apply safe remediations
    APPROVE = "approve"  # propose everything, wait for a human


@dataclass
class HealEvent:
    id: int
    incident_seq: int
    kind: str
    target: str
    action: str
    auto: bool
    approved: bool | None = None  # None = pending, True = applied, False = rejected
    countdown: int = 0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "incident_seq": self.incident_seq,
            "kind": self.kind,
            "target": self.target,
            "action": self.action,
            "auto": self.auto,
            "approved": self.approved,
            "countdown": self.countdown,
        }


class SelfHealAgent:
    """Deterministic detect → diagnose → remediate loop over the fault engine."""

    def __init__(self, faults: FaultEngine, *, mode: HealMode = HealMode.AUTO) -> None:
        self.faults = faults
        self.mode = mode
        self.running = False
        self.state = AgentState.IDLE
        self.events: list[HealEvent] = []
        self._eid = 0
        self._seen: set[int] = set()

    def start(self) -> None:
        self.running = True
        self.state = AgentState.MONITORING

    def stop(self) -> None:
        self.running = False
        self.state = AgentState.IDLE

    def set_mode(self, mode: HealMode) -> None:
        self.mode = mode

    def tick(self) -> None:
        if not self.running:
            return
        self.state = AgentState.MONITORING
        # progress existing auto-heals first, then detect new incidents — so a freshly
        # detected event gets the full HEAL_DELAY (it isn't decremented on its detect tick).
        for ev in self.events:
            if ev.auto and ev.approved is None:
                ev.countdown -= 1
                if ev.countdown <= 0:
                    self._apply(ev)
        for inc in self.faults.open_incidents():
            if inc.seq not in self._seen:
                self._detect(inc)

    def _detect(self, inc) -> None:
        self._seen.add(inc.seq)
        auto = self.mode is HealMode.AUTO and inc.kind in _AUTO_SAFE
        self._eid += 1
        self.events.append(
            HealEvent(
                id=self._eid,
                incident_seq=inc.seq,
                kind=inc.kind,
                target=inc.target,
                action=REMEDIATION.get(inc.kind, "manual intervention required"),
                auto=auto,
                countdown=HEAL_DELAY_TICKS if auto else 0,
            )
        )

    def _apply(self, ev: HealEvent) -> None:
        # resolve() restores the affected units to RUNNING — that IS the heal (the
        # cascade reverses). Idempotent if a human already resolved it.
        self.state = AgentState.REMEDIATING
        self.faults.resolve(ev.incident_seq)
        ev.approved = True

    def _find(self, event_id: int) -> HealEvent:
        for ev in self.events:
            if ev.id == event_id:
                return ev
        raise KeyError(f"unknown heal event {event_id}")

    def approve(self, event_id: int) -> HealEvent:
        ev = self._find(event_id)
        if ev.approved is None:
            self._apply(ev)
        return ev

    def reject(self, event_id: int) -> HealEvent:
        ev = self._find(event_id)
        if ev.approved is None:
            ev.approved = False
        return ev

    def status(self) -> dict:
        return {
            "running": self.running,
            "state": self.state.value,
            "mode": self.mode.value,
            "events": [e.as_dict() for e in self.events],
            "pending": [e.as_dict() for e in self.events if e.approved is None],
        }
