"""Tests for the bring-up / bring-down sequencer — full line + branch coverage."""

from __future__ import annotations

import yaml
from refinery.model import load_topology
from refinery.sequencer import SeqMode, Sequencer
from refinery.sim import ElementState, RefinerySim


def _net(sid: str) -> dict:
    return {
        role: {
            "type": "switch" if role == "switch" else "workstation",
            "tag": f"{role}-{sid}",
            "signal": "x",
            "unit": "u",
            "normal": [0, 1],
        }
        for role in ("switch", "gateway", "hmi", "ews")
    }


def _drive(seq: Sequencer, sim: RefinerySim, cap: int = 300) -> int:
    """Tick until the sequencer returns to IDLE; return ticks used."""
    for n in range(1, cap + 1):
        sim.tick()
        seq.tick()
        if seq.mode is SeqMode.IDLE:
            return n
    raise AssertionError("sequencer did not settle within cap")


def _new() -> tuple[RefinerySim, Sequencer]:
    sim = RefinerySim.from_default(seed=0)
    return sim, Sequencer(sim)


# ---------------------------------------------------------------- ordering


def test_order_is_acyclic_and_utilities_first():
    sim, seq = _new()
    order = seq.order
    assert set(order) == set(sim.ref.units_by_id)
    # utilities + flare appear before any conversion unit
    pos = {uid: i for i, uid in enumerate(order)}
    assert pos["U-IA1"] < pos["U-900"] < pos["U-840"]  # air -> steam -> FCC
    assert pos["U-FL1"] < pos["U-840"]  # flare before FCC
    assert pos["U-110"] < pos["U-840"]  # crude before conversion


def test_prereqs_met_true_and_false():
    sim, seq = _new()
    # the air unit has no predecessors -> always met
    assert seq.prereqs_met("U-IA1") is True
    # FCC needs crude/steam/etc which are not running yet
    assert seq.prereqs_met("U-840") is False


# ---------------------------------------------------------------- bring-up


def test_bringup_brings_whole_plant_running():
    sim, seq = _new()
    seq.start_bringup()
    assert seq.mode is SeqMode.BRINGING_UP
    # all elements discovered, network gear running
    assert sim.elements["SW-S4"].state is ElementState.RUNNING
    ticks = _drive(seq, sim)
    assert seq.mode is SeqMode.IDLE
    assert all(seq.sim.unit_status(uid) == "running" for uid in seq.order)
    assert ticks < 300
    # blocked clears once everything is up
    assert seq.status()["blocked"] is None


def test_bringup_reports_blocked_early():
    sim, seq = _new()
    seq.start_bringup()
    # first tick: downstream units are blocked waiting on utilities
    sim.tick()
    seq.tick()
    st = seq.status()
    assert st["mode"] == "bringing_up"
    assert st["blocked"] is not None
    assert "waiting on" in st["blocked"]["reason"]


# ---------------------------------------------------------------- bring-down


def test_bringdown_shuts_plant_in_reverse():
    sim, seq = _new()
    seq.start_bringup()
    _drive(seq, sim)
    assert all(sim.unit_status(uid) == "running" for uid in seq.order)

    seq.start_bringdown()
    assert seq.mode is SeqMode.BRINGING_DOWN
    ticks = _drive(seq, sim)
    assert seq.mode is SeqMode.IDLE
    assert all(sim.unit_status(uid) == "offline" for uid in seq.order)
    # network gear shut last
    assert sim.elements["SW-S4"].state is ElementState.OFFLINE
    # shutdown peels over several ticks (leaf-first), not a single collapse
    assert ticks > 1


def test_bringdown_shuts_leaf_before_utilities():
    sim, seq = _new()
    seq.start_bringup()
    _drive(seq, sim)
    # one bring-down tick: leaf (blender) shuts, utilities (steam) still running
    seq.start_bringdown()
    sim.tick()
    seq.tick()
    assert sim.unit_status("U-BL1") == "offline"
    assert sim.unit_status("U-900") == "running"


# ---------------------------------------------------------------- idle / status


def test_tick_idle_is_noop():
    sim, seq = _new()
    before = {t: rt.state for t, rt in sim.elements.items()}
    seq.tick()  # IDLE -> neither branch
    assert seq.mode is SeqMode.IDLE
    assert {t: rt.state for t, rt in sim.elements.items()} == before


def test_status_shape():
    sim, seq = _new()
    st = seq.status()
    assert st["mode"] == "idle"
    assert st["units_total"] == len(seq.order)
    assert st["units_running"] == 0
    assert st["blocked"] is None


def test_self_gate_requirement_is_skipped(tmp_path):
    """A unit whose interlock requires itself must not get a self-loop edge."""
    topo = {
        "refinery": {"name": "T", "crude_capacity_bpd": 1},
        "utilities": [],
        "interlocks": [{"id": "sg", "requires": ["U-X"], "gates": "selfgate"}],
        "sections": [
            {
                "id": "S1",
                "name": "S1",
                "bringup_order": 1,
                "network": _net("S1"),
                "units": [
                    {
                        "id": "U-X",
                        "name": "X",
                        "kind": "utility",
                        "gates": ["selfgate"],
                        "elements": [
                            {
                                "type": "sensor",
                                "tag": "TT-X",
                                "signal": "t",
                                "unit": "degC",
                                "normal": [0, 10],
                            },
                        ],
                    }
                ],
            }
        ],
    }
    p = tmp_path / "selfgate.yaml"
    p.write_text(yaml.safe_dump(topo))
    sim = RefinerySim(load_topology(p))
    seq = Sequencer(sim)  # must not raise (no self-loop -> no cycle)
    assert not seq._g.has_edge("U-X", "U-X")
    assert seq.order == ["U-X"]
