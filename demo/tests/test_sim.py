"""Tests for the refinery runtime — full line + branch coverage."""

from __future__ import annotations

import random

import pytest
from refinery.model import Element
from refinery.sim import (
    ElementRuntime,
    ElementState,
    RefinerySim,
    _rollup,
)


def _el(**kw) -> Element:
    base = dict(
        type="sensor",
        tag="TT-1",
        signal="temp",
        unit="degC",
        normal=(100.0, 200.0),
        section_id="S1",
        unit_id="U-1",
    )
    base.update(kw)
    return Element(**base)


def _rt(**kw) -> ElementRuntime:
    return ElementRuntime(_el(**kw))


# ---------------------------------------------------------------- ElementRuntime


def test_target_uses_setpoint_then_midpoint():
    assert _rt(setpoint=150.0).target == 150.0
    assert _rt().target == 150.0  # midpoint of (100,200)
    assert _rt(normal=(0.0, 10.0)).target == 5.0


def test_running_value_in_band_and_deterministic():
    rt = _rt(setpoint=150.0)
    rt.state = ElementState.RUNNING
    rng = random.Random(0)
    rt.tick(rng)
    assert 100.0 <= rt.value <= 200.0
    # same seed -> same value
    rt2 = _rt(setpoint=150.0)
    rt2.state = ElementState.RUNNING
    assert rt2._running_value(random.Random(0)) == rt._running_value(random.Random(0))


def test_running_value_clamped_to_band():
    # setpoint at the top edge + positive noise must still clamp to hi
    rt = _rt(normal=(0.0, 1.0), setpoint=1.0)
    rt.state = ElementState.RUNNING
    for seed in range(20):
        rt.tick(random.Random(seed))
        assert 0.0 <= rt.value <= 1.0


def test_sis_running_and_tripped_values():
    rt = _rt(type="sis", tag="SIS-1", signal="state", unit="sif", normal=(0.0, 0.0), trip_high=1.0)
    rt.state = ElementState.RUNNING
    rt.tick(random.Random(0))
    assert rt.value == 0.0  # armed, not tripped
    rt.state = ElementState.TRIPPED
    rt.tick(random.Random(0))
    assert rt.value == 1.0  # safe-state asserted
    assert rt.in_trip is True


def test_starting_ramps_then_ready():
    from refinery.sim import RAMP_TICKS

    rt = _rt(setpoint=150.0)
    rt.state = ElementState.STARTING
    assert rt.ready is False
    rng = random.Random(1)
    for _ in range(RAMP_TICKS):
        rt.tick(rng)
    assert rt.ready is True
    assert rt.ramp == pytest.approx(1.0)
    assert 100.0 <= rt.value <= 200.0


def test_stopping_cools_down_then_stopped():
    from refinery.sim import RAMP_TICKS

    rt = _rt(setpoint=150.0)
    rt.ramp = 1.0
    rt.state = ElementState.STOPPING
    assert rt.stopped is False
    rng = random.Random(2)
    for _ in range(RAMP_TICKS):
        rt.tick(rng)
    assert rt.stopped is True
    assert rt.ramp == pytest.approx(0.0)
    assert rt.value <= 110.0  # cooled to the low end of the operating band


def test_set_stopping_starts_at_full_ramp():
    from refinery.sim import ElementState as ES
    from refinery.sim import RefinerySim

    sim = RefinerySim.from_default()
    tag = next(iter(sim.elements))
    sim.set_element_state(tag, ES.STOPPING)
    assert sim.elements[tag].ramp == 1.0


def test_starting_sis_value_zero():
    rt = _rt(type="sis", tag="SIS-2", signal="state", unit="sif", normal=(0.0, 0.0))
    rt.state = ElementState.STARTING
    rt.tick(random.Random(0))
    assert rt.value == 0.0


def test_tripped_nonsis_goes_to_zero():
    rt = _rt(setpoint=150.0)
    rt.state = ElementState.TRIPPED
    rt.tick(random.Random(0))
    assert rt.value == 0.0


@pytest.mark.parametrize(
    "state", [ElementState.OFFLINE, ElementState.DISCOVERED, ElementState.DOWN]
)
def test_idle_states_read_zero(state):
    rt = _rt(setpoint=150.0)
    rt.value = 999.0
    rt.state = state
    rt.tick(random.Random(0))
    assert rt.value == 0.0


def test_alarm_and_trip_only_when_live():
    rt = _rt(alarm_high=180.0, trip_high=195.0, alarm_low=110.0, trip_low=105.0)
    rt.value = 190.0
    rt.state = ElementState.RUNNING
    assert rt.in_alarm is True
    assert rt.in_trip is False
    rt.value = 196.0
    assert rt.in_trip is True
    # low side
    rt.value = 108.0
    assert rt.in_alarm is True
    rt.value = 104.0
    assert rt.in_trip is True
    # not live -> never alarms even with a bad value
    rt.state = ElementState.DISCOVERED
    assert rt.in_alarm is False
    assert rt.in_trip is False


def test_alarm_false_when_no_thresholds():
    rt = _rt()  # no alarm_high/low
    rt.value = 1e9
    rt.state = ElementState.RUNNING
    assert rt.in_alarm is False
    assert rt.in_trip is False


# ---------------------------------------------------------------- RefinerySim


def test_from_default_builds_full_fleet():
    sim = RefinerySim.from_default(seed=0)
    assert len(sim.elements) >= 80
    assert all(rt.state is ElementState.OFFLINE for rt in sim.elements.values())


def test_runtime_unknown_tag_raises():
    sim = RefinerySim.from_default()
    with pytest.raises(KeyError, match="unknown element tag"):
        sim.runtime("NOPE")


def test_set_element_state_resets_ramp_on_starting():
    sim = RefinerySim.from_default()
    tag = next(iter(sim.elements))
    sim.elements[tag].ramp = 0.8
    sim.set_element_state(tag, ElementState.STARTING)
    assert sim.elements[tag].ramp == 0.0
    sim.set_element_state(tag, ElementState.RUNNING)
    assert sim.elements[tag].state is ElementState.RUNNING


def test_set_unit_state_known_and_unknown():
    sim = RefinerySim.from_default()
    sim.set_unit_state("U-840", ElementState.RUNNING)
    fcc = sim.ref.units_by_id["U-840"]
    assert all(sim.elements[e.tag].state is ElementState.RUNNING for e in fcc.elements)
    with pytest.raises(KeyError, match="unknown unit"):
        sim.set_unit_state("U-GHOST", ElementState.RUNNING)


def test_set_section_network_state_known_and_unknown():
    sim = RefinerySim.from_default()
    sim.set_section_network_state("S2", ElementState.RUNNING)
    net = sim.ref.sections_by_id["S2"].network
    assert all(sim.elements[e.tag].state is ElementState.RUNNING for e in net.values())
    with pytest.raises(KeyError, match="unknown section"):
        sim.set_section_network_state("S9", ElementState.RUNNING)


def test_discover_all_and_tick():
    sim = RefinerySim.from_default()
    sim.discover_all()
    assert all(rt.state is ElementState.DISCOVERED for rt in sim.elements.values())
    sim.tick()  # discovered -> reads zero, no crash
    assert all(rt.value == 0.0 for rt in sim.elements.values())


def test_unit_status_rollup():
    sim = RefinerySim.from_default()
    sim.set_unit_state("U-840", ElementState.RUNNING)
    assert sim.unit_status("U-840") == "running"


def test_signals_shape_and_counts():
    sim = RefinerySim.from_default(seed=3)
    sim.discover_all()
    sim.set_unit_state("U-900", ElementState.RUNNING)
    for _ in range(3):
        sim.tick()
    sig = sim.signals()
    assert sig["elements_total"] == len(sim.elements)
    assert "discovered" in sig["by_state"]
    assert sig["units_total"] == len(sim.ref.units_by_id)
    assert sig["units_running"] >= 1
    assert set(sig["sections"]) == {"S1", "S2", "S3", "S4", "S5"}
    s4 = sig["sections"]["S4"]
    assert s4["total"] > 0 and 0 <= s4["running"] <= s4["total"]
    assert isinstance(sig["alarms"], list) and isinstance(sig["trips"], list)


def test_signals_reports_alarms_and_trips():
    sim = RefinerySim.from_default(seed=0)
    # force a pump into trip via a bad value while live
    tag = "P-9005"
    sim.set_element_state(tag, ElementState.RUNNING)
    sim.elements[tag].value = 999.0  # > trip_high 7.1
    sig = sim.signals()
    assert tag in sig["trips"]
    assert tag in sig["alarms"]


# ---------------------------------------------------------------- _rollup


def test_rollup_all_branches():
    R = ElementState
    assert _rollup([]) == "offline"
    assert _rollup([R.RUNNING, R.DOWN]) == "down"
    assert _rollup([R.RUNNING, R.TRIPPED]) == "tripped"
    assert _rollup([R.RUNNING, R.STOPPING]) == "stopping"
    assert _rollup([R.RUNNING, R.STARTING]) == "starting"
    assert _rollup([R.RUNNING, R.RUNNING]) == "running"
    assert _rollup([R.RUNNING, R.DISCOVERED]) == "partial"
    assert _rollup([R.DISCOVERED, R.DISCOVERED]) == "discovered"
    assert _rollup([R.OFFLINE, R.DISCOVERED]) == "offline"
