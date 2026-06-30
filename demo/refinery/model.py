"""Refinery topology model — the frozen contract loaded from a topology YAML.

Pure, static structure: sections -> units -> elements, plus the dependency graph
(process FEEDS + utility CONSUMES) used for bring-up sequencing and fault cascade.
Runtime state (live telemetry, element modes) lives in :mod:`refinery.sim`, not here.

Modeled on ExxonMobil Baytown using public data only; element tags are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

VALID_ELEMENT_TYPES = frozenset(
    {
        "sensor",
        "gas",
        "valve",
        "mov",
        "pump",
        "plc",
        "dcs",
        "sis",
        "switch",
        "gateway",
        "workstation",
        "rtu",
    }
)

NETWORK_ROLES = ("switch", "gateway", "hmi", "ews")


class TopologyError(ValueError):
    """Raised when a topology file violates the frozen contract."""


@dataclass(frozen=True)
class Element:
    """A single registerable refinery device (sensor, valve, PLC, switch, ...)."""

    type: str
    tag: str
    signal: str
    unit: str
    normal: tuple[float, float]
    section_id: str
    unit_id: str
    setpoint: float | None = None
    alarm_high: float | None = None
    alarm_low: float | None = None
    trip_high: float | None = None
    trip_low: float | None = None

    @property
    def agent_id(self) -> str:
        """Registry primary key: ``<type>.<section>.<tag>`` (see PLAN §4)."""
        return f"{self.type}.{self.section_id}.{self.tag}"

    @property
    def capabilities(self) -> list[str]:
        """Free-form tags carried through the real Registry (no schema change)."""
        return [
            f"type:{self.type}",
            f"section:{self.section_id}",
            f"unit:{self.unit_id}",
            f"tag:{self.tag}",
            f"signal:{self.signal}",
        ]


@dataclass(frozen=True)
class Unit:
    """A process unit (Pipestill, FCC, Hydrotreater, Boiler House, ...)."""

    id: str
    name: str
    kind: str
    section_id: str
    gates: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    elements: tuple[Element, ...] = ()


@dataclass(frozen=True)
class Section:
    """An operational section — a Purdue cell with shared network gear."""

    id: str
    name: str
    bringup_order: int
    network: dict[str, Element]
    units: tuple[Unit, ...]

    @property
    def all_elements(self) -> list[Element]:
        out: list[Element] = list(self.network.values())
        for u in self.units:
            out.extend(u.elements)
        return out


@dataclass(frozen=True)
class Interlock:
    """A hard bring-up gate: units carrying ``gates`` tag wait on ``requires``."""

    id: str
    requires: tuple[str, ...]
    gates: str


@dataclass
class Refinery:
    """The whole modeled plant plus its derived dependency graph."""

    name: str
    crude_capacity_bpd: int
    utilities: tuple[str, ...]
    interlocks: tuple[Interlock, ...]
    sections: tuple[Section, ...]
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)

    # -- derived lookups -------------------------------------------------
    @property
    def units_by_id(self) -> dict[str, Unit]:
        return {u.id: u for s in self.sections for u in s.units}

    @property
    def sections_by_id(self) -> dict[str, Section]:
        return {s.id: s for s in self.sections}

    @property
    def elements_by_tag(self) -> dict[str, Element]:
        out: dict[str, Element] = {}
        for s in self.sections:
            for e in s.all_elements:
                out[e.tag] = e
        return out

    @property
    def all_elements(self) -> list[Element]:
        return [e for s in self.sections for e in s.all_elements]

    def gate_requirements(self, gate: str) -> list[str]:
        """Unit ids that must be RUNNING before any unit with this gate tag starts."""
        req: list[str] = []
        for il in self.interlocks:
            if il.gates == gate:
                req.extend(il.requires)
        return req

    def utility_providers(self, utility: str) -> list[str]:
        """Unit ids that produce a given utility resource."""
        return [u.id for u in self.units_by_id.values() if utility in u.provides]


def _as_tuple(value: Any) -> tuple:
    if value is None:
        return ()
    return tuple(value)


def _parse_element(raw: dict[str, Any], section_id: str, unit_id: str) -> Element:
    try:
        etype = raw["type"]
        tag = raw["tag"]
        signal = raw["signal"]
        unit = raw["unit"]
        normal = raw["normal"]
    except KeyError as exc:
        raise TopologyError(f"element in {unit_id} missing key {exc}") from exc
    if etype not in VALID_ELEMENT_TYPES:
        raise TopologyError(f"element {tag}: unknown type '{etype}'")
    if not (isinstance(normal, list) and len(normal) == 2):
        raise TopologyError(f"element {tag}: 'normal' must be [low, high]")
    lo, hi = float(normal[0]), float(normal[1])
    if lo > hi:
        raise TopologyError(f"element {tag}: normal low {lo} > high {hi}")
    return Element(
        type=etype,
        tag=tag,
        signal=signal,
        unit=unit,
        normal=(lo, hi),
        section_id=section_id,
        unit_id=unit_id,
        setpoint=raw.get("setpoint"),
        alarm_high=raw.get("alarm_high"),
        alarm_low=raw.get("alarm_low"),
        trip_high=raw.get("trip_high"),
        trip_low=raw.get("trip_low"),
    )


def _parse_unit(raw: dict[str, Any], section_id: str) -> Unit:
    uid = raw["id"]
    elements = tuple(_parse_element(e, section_id, uid) for e in raw.get("elements", []))
    return Unit(
        id=uid,
        name=raw["name"],
        kind=raw["kind"],
        section_id=section_id,
        gates=_as_tuple(raw.get("gates")),
        provides=_as_tuple(raw.get("provides")),
        consumes=_as_tuple(raw.get("consumes")),
        feeds=_as_tuple(raw.get("feeds")),
        elements=elements,
    )


def _parse_section(raw: dict[str, Any]) -> Section:
    sid = raw["id"]
    net_raw = raw.get("network", {})
    for role in NETWORK_ROLES:
        if role not in net_raw:
            raise TopologyError(f"section {sid}: network missing role '{role}'")
    network = {role: _parse_element(net_raw[role], sid, f"{sid}-net") for role in NETWORK_ROLES}
    units = tuple(_parse_unit(u, sid) for u in raw.get("units", []))
    return Section(
        id=sid,
        name=raw["name"],
        bringup_order=int(raw["bringup_order"]),
        network=network,
        units=units,
    )


def _build_graph(ref: Refinery) -> nx.DiGraph:
    """Unit dependency graph: FEEDS (process) + CONSUMES (utility) edges.

    An edge ``a -> b`` means *b depends on a* — a's loss can cascade to b.
    """
    g = nx.DiGraph()
    units = ref.units_by_id
    for uid in units:
        g.add_node(uid)
    for u in units.values():
        for downstream in u.feeds:
            g.add_edge(u.id, downstream, kind="feeds")
        for utility in u.consumes:
            for provider in ref.utility_providers(utility):
                g.add_edge(provider, u.id, kind="utility", resource=utility)
    return g


def _validate(ref: Refinery) -> None:
    orders = [s.bringup_order for s in ref.sections]
    if len(set(orders)) != len(orders):
        raise TopologyError("duplicate section bringup_order")

    unit_ids = [u.id for s in ref.sections for u in s.units]
    if len(set(unit_ids)) != len(unit_ids):
        raise TopologyError("duplicate unit id")
    known_units = set(unit_ids)

    tags = [e.tag for s in ref.sections for e in s.all_elements]
    if len(set(tags)) != len(tags):
        raise TopologyError("duplicate element tag")

    for il in ref.interlocks:
        for req in il.requires:
            if req not in known_units:
                raise TopologyError(f"interlock {il.id} requires unknown unit '{req}'")

    for u in ref.units_by_id.values():
        for downstream in u.feeds:
            if downstream not in known_units:
                raise TopologyError(f"unit {u.id} feeds unknown unit '{downstream}'")
        for utility in u.consumes:
            if utility not in ref.utilities:
                raise TopologyError(f"unit {u.id} consumes unknown utility '{utility}'")
            if not ref.utility_providers(utility):
                raise TopologyError(f"utility '{utility}' has no provider")
        for utility in u.provides:
            if utility not in ref.utilities:
                raise TopologyError(f"unit {u.id} provides unknown utility '{utility}'")


def load_topology(path: str | Path) -> Refinery:
    """Parse and validate a topology YAML into a :class:`Refinery`."""
    path = Path(path)
    if not path.exists():
        raise TopologyError(f"topology file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    rmeta = raw["refinery"]
    interlocks = tuple(
        Interlock(id=i["id"], requires=_as_tuple(i["requires"]), gates=i["gates"])
        for i in raw.get("interlocks", [])
    )
    sections = tuple(
        sorted(
            (_parse_section(s) for s in raw.get("sections", [])),
            key=lambda s: s.bringup_order,
        )
    )
    ref = Refinery(
        name=rmeta["name"],
        crude_capacity_bpd=int(rmeta["crude_capacity_bpd"]),
        utilities=_as_tuple(raw.get("utilities")),
        interlocks=interlocks,
        sections=sections,
    )
    _validate(ref)
    ref.graph = _build_graph(ref)
    return ref


def default_topology_path() -> Path:
    return Path(__file__).parent / "topology" / "baytown.yaml"
