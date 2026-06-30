"""Tests for the refinery topology model — full line + branch coverage."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from refinery.model import (
    Element,
    TopologyError,
    default_topology_path,
    load_topology,
)


def _min_topo() -> dict:
    """A minimal, valid topology exercising provider/consumer/feeds edges."""
    return {
        "refinery": {"name": "Test", "crude_capacity_bpd": 1000},
        "utilities": ["steam"],
        "interlocks": [{"id": "steam_available", "requires": ["U-BOIL"], "gates": "fired"}],
        "sections": [
            {
                "id": "S4",
                "name": "Utilities",
                "bringup_order": 1,
                "network": {
                    "switch": {
                        "type": "switch",
                        "tag": "SW-S4",
                        "signal": "tp",
                        "unit": "Mbps",
                        "normal": [0, 100],
                    },
                    "gateway": {
                        "type": "gateway",
                        "tag": "GW-S4",
                        "signal": "s",
                        "unit": "c",
                        "normal": [0, 10],
                    },
                    "hmi": {
                        "type": "workstation",
                        "tag": "HMI-S4",
                        "signal": "a",
                        "unit": "c",
                        "normal": [0, 4],
                    },
                    "ews": {
                        "type": "workstation",
                        "tag": "EWS-S4",
                        "signal": "cpu",
                        "unit": "pct",
                        "normal": [0, 40],
                    },
                },
                "units": [
                    {
                        "id": "U-BOIL",
                        "name": "Boiler",
                        "kind": "utility",
                        "provides": ["steam"],
                        "feeds": ["U-CDU"],
                        "elements": [
                            {
                                "type": "sensor",
                                "tag": "PT-1",
                                "signal": "pressure",
                                "unit": "bar",
                                "normal": [40, 46],
                                "setpoint": 43,
                                "trip_high": 55,
                            },
                        ],
                    }
                ],
            },
            {
                "id": "S1",
                "name": "Crude",
                "bringup_order": 2,
                "network": {
                    "switch": {
                        "type": "switch",
                        "tag": "SW-S1",
                        "signal": "tp",
                        "unit": "Mbps",
                        "normal": [0, 100],
                    },
                    "gateway": {
                        "type": "gateway",
                        "tag": "GW-S1",
                        "signal": "s",
                        "unit": "c",
                        "normal": [0, 10],
                    },
                    "hmi": {
                        "type": "workstation",
                        "tag": "HMI-S1",
                        "signal": "a",
                        "unit": "c",
                        "normal": [0, 4],
                    },
                    "ews": {
                        "type": "workstation",
                        "tag": "EWS-S1",
                        "signal": "cpu",
                        "unit": "pct",
                        "normal": [0, 40],
                    },
                },
                "units": [
                    {
                        "id": "U-CDU",
                        "name": "Crude",
                        "kind": "separation",
                        "gates": ["fired"],
                        "consumes": ["steam"],
                        "elements": [
                            {
                                "type": "sensor",
                                "tag": "TT-1",
                                "signal": "temp",
                                "unit": "degC",
                                "normal": [330, 360],
                            },
                        ],
                    }
                ],
            },
        ],
    }


def _write(tmp_path: Path, topo: dict) -> Path:
    p = tmp_path / "topo.yaml"
    p.write_text(yaml.safe_dump(topo))
    return p


# ---------------------------------------------------------------- happy path


def test_load_default_baytown_topology():
    ref = load_topology(default_topology_path())
    assert ref.name == "Baytown (modeled)"
    assert ref.crude_capacity_bpd == 588000
    assert len(ref.sections) == 5
    # sorted by bringup_order: utilities first, storage last
    assert [s.id for s in ref.sections] == ["S4", "S1", "S3", "S2", "S5"]
    # a realistic element count for a believable fleet
    assert 80 <= len(ref.all_elements) <= 160
    # every element belongs to a real section + has a sane band
    for e in ref.all_elements:
        lo, hi = e.normal
        assert lo <= hi
        assert e.section_id in ref.sections_by_id


def test_derived_lookups_and_gate_requirements():
    ref = load_topology(default_topology_path())
    assert "U-840" in ref.units_by_id
    assert ref.units_by_id["U-840"].name.startswith("Fluid Catalytic")
    # conversion gate requires the three crude pipestills running
    assert set(ref.gate_requirements("conversion")) == {"U-110", "U-120", "U-135"}
    assert ref.gate_requirements("nonexistent-gate") == []
    assert "U-900" in ref.utility_providers("steam")


def test_graph_has_feeds_and_utility_edges():
    ref = load_topology(default_topology_path())
    g = ref.graph
    # process feed: a pipestill feeds the FCC
    assert g.has_edge("U-110", "U-840")
    assert g.edges["U-110", "U-840"]["kind"] == "feeds"
    # utility: the boiler (steam) feeds the FCC as a dependency
    assert g.has_edge("U-900", "U-840")
    assert g.edges["U-900", "U-840"]["kind"] == "utility"
    assert g.edges["U-900", "U-840"]["resource"] == "steam"


def test_element_agent_id_and_capabilities():
    e = Element(
        type="sensor",
        tag="PT-101",
        signal="pressure",
        unit="bar",
        normal=(1.0, 2.0),
        section_id="S1",
        unit_id="U-110",
    )
    assert e.agent_id == "sensor.S1.PT-101"
    assert "type:sensor" in e.capabilities
    assert "section:S1" in e.capabilities
    assert "tag:PT-101" in e.capabilities


def test_section_all_elements_includes_network_gear(tmp_path):
    ref = load_topology(_write(tmp_path, _min_topo()))
    s4 = ref.sections_by_id["S4"]
    tags = {e.tag for e in s4.all_elements}
    assert {"SW-S4", "GW-S4", "HMI-S4", "EWS-S4", "PT-1"} <= tags
    assert ref.elements_by_tag["PT-1"].trip_high == 55


# ---------------------------------------------------------------- validation


def test_missing_file():
    with pytest.raises(TopologyError, match="not found"):
        load_topology("/no/such/topology.yaml")


def test_duplicate_bringup_order(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["bringup_order"] = 1
    with pytest.raises(TopologyError, match="duplicate section bringup_order"):
        load_topology(_write(tmp_path, topo))


def test_duplicate_unit_id(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["units"][0]["id"] = "U-BOIL"
    with pytest.raises(TopologyError, match="duplicate unit id"):
        load_topology(_write(tmp_path, topo))


def test_duplicate_element_tag(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["units"][0]["elements"][0]["tag"] = "PT-1"
    with pytest.raises(TopologyError, match="duplicate element tag"):
        load_topology(_write(tmp_path, topo))


def test_interlock_unknown_unit(tmp_path):
    topo = _min_topo()
    topo["interlocks"][0]["requires"] = ["U-GHOST"]
    with pytest.raises(TopologyError, match="requires unknown unit"):
        load_topology(_write(tmp_path, topo))


def test_feeds_unknown_unit(tmp_path):
    topo = _min_topo()
    topo["sections"][0]["units"][0]["feeds"] = ["U-GHOST"]
    with pytest.raises(TopologyError, match="feeds unknown unit"):
        load_topology(_write(tmp_path, topo))


def test_consumes_unknown_utility(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["units"][0]["consumes"] = ["plasma"]
    with pytest.raises(TopologyError, match="unknown utility"):
        load_topology(_write(tmp_path, topo))


def test_utility_with_no_provider(tmp_path):
    topo = _min_topo()
    # declare a utility nobody provides, but a unit consumes
    topo["utilities"] = ["steam", "nitrogen"]
    topo["sections"][1]["units"][0]["consumes"] = ["nitrogen"]
    with pytest.raises(TopologyError, match="no provider"):
        load_topology(_write(tmp_path, topo))


def test_provides_unknown_utility(tmp_path):
    topo = _min_topo()
    topo["sections"][0]["units"][0]["provides"] = ["steam", "magic"]
    with pytest.raises(TopologyError, match="provides unknown utility"):
        load_topology(_write(tmp_path, topo))


# ---------------------------------------------------------------- element parse


def test_element_missing_key(tmp_path):
    topo = _min_topo()
    del topo["sections"][1]["units"][0]["elements"][0]["signal"]
    with pytest.raises(TopologyError, match="missing key"):
        load_topology(_write(tmp_path, topo))


def test_element_unknown_type(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["units"][0]["elements"][0]["type"] = "reactor"
    with pytest.raises(TopologyError, match="unknown type"):
        load_topology(_write(tmp_path, topo))


def test_element_bad_normal_shape(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["units"][0]["elements"][0]["normal"] = [5]
    with pytest.raises(TopologyError, match="must be"):
        load_topology(_write(tmp_path, topo))


def test_element_inverted_normal(tmp_path):
    topo = _min_topo()
    topo["sections"][1]["units"][0]["elements"][0]["normal"] = [400, 300]
    with pytest.raises(TopologyError, match="low .* > high"):
        load_topology(_write(tmp_path, topo))


def test_section_network_missing_role(tmp_path):
    topo = _min_topo()
    del topo["sections"][0]["network"]["gateway"]
    with pytest.raises(TopologyError, match="network missing role 'gateway'"):
        load_topology(_write(tmp_path, topo))


def test_units_without_elements_key(tmp_path):
    """A unit with no 'elements' key parses to an empty tuple (default branch)."""
    topo = _min_topo()
    del topo["sections"][0]["units"][0]["elements"]
    ref = load_topology(_write(tmp_path, topo))
    assert ref.units_by_id["U-BOIL"].elements == ()


def test_default_topology_path_points_at_baytown():
    assert default_topology_path().name == "baytown.yaml"
    assert default_topology_path().exists()


def test_min_topo_roundtrip_is_deep_copyable():
    """Guard the fixture itself stays independent across mutations."""
    a = _min_topo()
    b = copy.deepcopy(a)
    a["sections"][0]["units"][0]["id"] = "CHANGED"
    assert b["sections"][0]["units"][0]["id"] == "U-BOIL"
