"""Tests for gradual fault propagation + recovery — full line + branch coverage."""

from __future__ import annotations

import pytest
from refinery.faults import FAULT_KINDS, FaultEngine, Incident
from refinery.sim import ElementState, RefinerySim


def _running_sim() -> RefinerySim:
    sim = RefinerySim.from_default(seed=0)
    for uid in sim.ref.units_by_id:
        sim.set_unit_state(uid, ElementState.RUNNING)
    for s in sim.ref.sections:
        sim.set_section_network_state(s.id, ElementState.RUNNING)
    return sim


def _spread(fe: FaultEngine, inc: Incident) -> None:
    """Tick until the incident's cascade has fully propagated."""
    for _ in range(len(inc.plan) + 1):
        fe.tick()


# ---------------------------------------------------------------- gradual cascade


def test_unit_trip_propagates_over_ticks():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("unit_trip", "U-900")  # steam — feeds much of the plant
    assert sim.unit_status("U-900") == "tripped"  # origin fails immediately
    assert sim.unit_status("U-950") == "running"  # downstream NOT down yet
    assert inc.applied == 1 and len(inc.plan) > 1
    _spread(fe, inc)
    assert inc.applied == len(inc.plan)
    assert sim.unit_status("U-950") == "tripped"  # cascaded after ticks
    assert len(inc.affected) > 1


def test_loss_and_gas_reasons_and_descriptions():
    sim = _running_sim()
    fe = FaultEngine(sim)
    a = fe.inject("loss_of_utility", "U-CT1")
    assert "loss of utility" in a.description
    b = fe.inject("gas_release", "U-840")
    assert "gas release" in b.description


def test_cascade_plan_only_includes_running():
    # only steam running; its descendants are offline -> nothing to cascade
    sim = RefinerySim.from_default(seed=0)
    sim.set_unit_state("U-900", ElementState.RUNNING)
    fe = FaultEngine(sim)
    inc = fe.inject("unit_trip", "U-900")
    assert inc.plan == [("U-900", "tripped")]
    assert inc.affected == ["U-900"]


def test_unit_trip_unknown_unit():
    fe = FaultEngine(_running_sim())
    with pytest.raises(KeyError, match="unknown unit"):
        fe.inject("unit_trip", "U-GHOST")


# ---------------------------------------------------------------- switch / pump / element


def test_switch_down_blinds_section_gradually():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("switch_down", "S2")
    assert sim.elements["SW-S2"].state is ElementState.DOWN  # switch dies first
    assert sim.unit_status("U-840") == "running"  # section units not yet
    _spread(fe, inc)
    assert sim.unit_status("U-840") == "down"
    assert "SW-S2" in inc.affected and "U-840" in inc.affected


def test_switch_down_unknown_section():
    fe = FaultEngine(_running_sim())
    with pytest.raises(KeyError, match="unknown section"):
        fe.inject("switch_down", "S9")


def test_pump_vibration_downs_unit_then_cascades():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("pump_vibration", "P-9005")  # boiler-house pump
    assert sim.elements["P-9005"].state is ElementState.DOWN
    assert sim.unit_status("U-900") == "down"  # rollup: a down pump downs the unit
    assert inc.affected[0] == "P-9005"
    _spread(fe, inc)
    assert sim.unit_status("U-950") == "tripped"  # a steam consumer cascaded


def test_pump_vibration_on_non_pump():
    fe = FaultEngine(_running_sim())
    with pytest.raises(ValueError, match="not a pump"):
        fe.inject("pump_vibration", "TT-9003")


def test_element_offline_is_single_and_immediate():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("element_offline", "TT-1101")
    assert sim.elements["TT-1101"].state is ElementState.DOWN
    assert inc.plan == [("TT-1101", "down")] and inc.applied == 1
    assert "heartbeat lost" in inc.description


def test_unknown_kind():
    fe = FaultEngine(_running_sim())
    with pytest.raises(ValueError, match="unknown fault kind"):
        fe.inject("meltdown", "U-840")


# ---------------------------------------------------------------- gradual recovery


def test_recovery_rolls_back_gradually():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("unit_trip", "U-900")
    _spread(fe, inc)
    assert inc.applied == len(inc.plan)

    fe.resolve(inc.seq)
    assert inc.resolving and not inc.resolved
    assert fe.open_incidents() == [inc]  # still open while recovering
    fe.resolve(inc.seq)  # idempotent — already resolving
    for _ in range(inc.applied + 1):
        fe.tick()
    assert inc.resolved
    assert sim.unit_status("U-900") == "running"
    assert sim.unit_status("U-950") == "running"
    assert fe.open_incidents() == []


def test_resolve_unknown_incident():
    fe = FaultEngine(_running_sim())
    with pytest.raises(KeyError, match="unknown incident"):
        fe.resolve(999)


def test_resolved_incident_tick_is_noop():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("element_offline", "TT-1101")
    fe.resolve(inc.seq)
    fe.tick()  # restores the single item -> resolved
    assert inc.resolved
    fe.tick()  # already resolved -> skipped (no error)
    assert inc.resolved


# ---------------------------------------------------------------- misc


def test_incident_as_dict_and_kinds():
    inc = Incident(1, "unit_trip", "U-840", "desc", [("U-840", "tripped")], applied=1)
    d = inc.as_dict()
    assert d["seq"] == 1 and d["affected"] == ["U-840"]
    assert d["applied"] == 1 and d["resolved"] is False and d["resolving"] is False
    assert "switch_down" in FAULT_KINDS
    assert FAULT_KINDS["pump_vibration"]["target"] == "pump"
