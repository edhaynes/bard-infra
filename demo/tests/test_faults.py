"""Tests for fault injection + cascade propagation — full line + branch coverage."""

from __future__ import annotations

import pytest
from refinery.faults import FAULT_KINDS, FaultEngine, Incident
from refinery.sim import ElementState, RefinerySim


def _running_sim() -> RefinerySim:
    """A sim with the whole plant running (so cascades have live dependents)."""
    sim = RefinerySim.from_default(seed=0)
    for uid in sim.ref.units_by_id:
        sim.set_unit_state(uid, ElementState.RUNNING)
    for s in sim.ref.sections:
        sim.set_section_network_state(s.id, ElementState.RUNNING)
    return sim


# ---------------------------------------------------------------- unit faults


def test_unit_trip_cascades_downstream():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("unit_trip", "U-900")  # steam: feeds much of the plant
    assert sim.unit_status("U-900") == "tripped"
    assert inc.target == "U-900"
    assert len(inc.affected) > 1  # downstream tripped too
    # a known steam consumer tripped
    assert any(sim.unit_status(u) == "tripped" for u in ("U-950", "U-110"))


def test_loss_of_utility_and_gas_release_reasons():
    sim = _running_sim()
    fe = FaultEngine(sim)
    a = fe.inject("loss_of_utility", "U-CT1")
    assert "loss of utility" in a.description
    b = fe.inject("gas_release", "U-840")
    assert "gas release" in b.description


def test_cascade_skips_non_running_dependents():
    # only steam running; its descendants are offline -> nothing to cascade
    sim = RefinerySim.from_default(seed=0)
    sim.set_unit_state("U-900", ElementState.RUNNING)
    fe = FaultEngine(sim)
    inc = fe.inject("unit_trip", "U-900")
    assert inc.affected == ["U-900"]


def test_unit_trip_unknown_unit():
    fe = FaultEngine(_running_sim())
    with pytest.raises(KeyError, match="unknown unit"):
        fe.inject("unit_trip", "U-GHOST")


# ---------------------------------------------------------------- switch / pump / element


def test_switch_down_blinds_section():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("switch_down", "S2")
    assert sim.elements["SW-S2"].state is ElementState.DOWN
    assert sim.unit_status("U-840") == "down"
    assert "SW-S2" in inc.affected and "U-840" in inc.affected


def test_switch_down_unknown_section():
    fe = FaultEngine(_running_sim())
    with pytest.raises(KeyError, match="unknown section"):
        fe.inject("switch_down", "S9")


def test_pump_vibration_trips_pump_and_unit():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("pump_vibration", "P-9005")  # boiler-house pump
    assert sim.elements["P-9005"].state is ElementState.DOWN
    assert sim.unit_status("U-900") == "down"  # pump dark within a tripped unit
    assert inc.affected[0] == "P-9005"


def test_pump_vibration_on_non_pump():
    fe = FaultEngine(_running_sim())
    with pytest.raises(ValueError, match="not a pump"):
        fe.inject("pump_vibration", "TT-9003")  # a sensor


def test_element_offline_marks_down():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("element_offline", "TT-1101")
    assert sim.elements["TT-1101"].state is ElementState.DOWN
    assert "heartbeat lost" in inc.description


def test_unknown_kind():
    fe = FaultEngine(_running_sim())
    with pytest.raises(ValueError, match="unknown fault kind"):
        fe.inject("meltdown", "U-840")


# ---------------------------------------------------------------- resolve


def test_resolve_restores_units_and_elements():
    sim = _running_sim()
    fe = FaultEngine(sim)
    inc = fe.inject("switch_down", "S2")  # affects both an element and units
    assert fe.open_incidents() == [inc]
    resolved = fe.resolve(inc.seq)
    assert resolved.resolved is True
    assert sim.elements["SW-S2"].state is ElementState.RUNNING
    assert sim.unit_status("U-840") == "running"
    assert fe.open_incidents() == []


def test_resolve_unknown_incident():
    fe = FaultEngine(_running_sim())
    with pytest.raises(KeyError, match="unknown incident"):
        fe.resolve(999)


# ---------------------------------------------------------------- misc


def test_incident_as_dict_and_kinds():
    inc = Incident(1, "unit_trip", "U-840", "desc", ["U-840"])
    d = inc.as_dict()
    assert d["seq"] == 1 and d["affected"] == ["U-840"] and d["resolved"] is False
    assert "switch_down" in FAULT_KINDS
    assert FAULT_KINDS["pump_vibration"]["target"] == "pump"
