"""Tests for the distributed fabric — replicated areas, failover, twin. Full coverage."""

from __future__ import annotations

import fnmatch

import pytest
from refinery.fabric import (
    InMemoryAreaStore,
    ReplicatedFabric,
    ValkeyAreaStore,
    default_fabric,
)


class FakeValkey:
    """Minimal dict-backed stand-in for the valkey-py client (no network)."""

    def __init__(self) -> None:
        self.d: dict[str, object] = {}

    def set(self, name, value):
        self.d[name] = value

    def get(self, name):
        return self.d.get(name)

    def keys(self, pattern):
        return [k for k in self.d if fnmatch.fnmatch(k, pattern)]


# ---------------------------------------------------------------- InMemoryAreaStore


def test_inmemory_write_read_count():
    a = InMemoryAreaStore("area-1")
    assert a.healthy is True
    assert a.read("x") is None
    a.write("x", {"v": 1})
    assert a.read("x") == {"v": 1}
    assert a.count() == 1
    a.set_healthy(False)
    assert a.healthy is False


# ---------------------------------------------------------------- ValkeyAreaStore


def test_valkey_store_str_and_bytes_and_missing():
    c = FakeValkey()
    s = ValkeyAreaStore("area-v", c)
    assert s.read("t") is None
    s.write("t", {"v": 2})
    assert s.read("t") == {"v": 2}  # stored as JSON str
    assert s.count() == 1
    # simulate a client that returns bytes (real valkey does)
    c.d["twin:b"] = b'{"v": 3}'
    assert s.read("b") == {"v": 3}


# ---------------------------------------------------------------- ReplicatedFabric


def test_fabric_requires_an_area():
    with pytest.raises(ValueError, match="at least one area"):
        ReplicatedFabric([])


def test_replicate_write_and_read_failover():
    a1, a2, a3 = (InMemoryAreaStore(f"area-{i}") for i in (1, 2, 3))
    fab = ReplicatedFabric([a1, a2, a3])
    assert fab.write("PT-1", {"v": 10}) == 3  # all healthy
    got = fab.read("PT-1")
    assert got["v"] == 10 and got["served_by"] == "area-1"

    # kill area-1 -> served by area-2 (failover); writes go to 2 areas
    fab.kill_area("area-1")
    assert fab.read("PT-1")["served_by"] == "area-2"
    assert fab.write("PT-2", {"v": 20}) == 2

    fab.restore_area("area-1")
    assert fab.read("PT-1")["served_by"] == "area-1"


def test_read_missing_returns_none():
    fab = ReplicatedFabric([InMemoryAreaStore("area-1")])
    assert fab.read("nope") is None


def test_twin_is_last_state_and_survives_area_loss():
    a1, a2 = InMemoryAreaStore("area-1"), InMemoryAreaStore("area-2")
    fab = ReplicatedFabric([a1, a2])
    fab.write("FV-1", {"value": 60, "state": "running"})
    # device "dies": we stop writing; the twin still holds the last state
    twin = fab.twin("FV-1")
    assert twin["value"] == 60 and twin["state"] == "running"
    # lose the area that served it -> twin still available from the replica
    fab.kill_area("area-1")
    assert fab.twin("FV-1")["value"] == 60


def test_unknown_area_raises():
    fab = ReplicatedFabric([InMemoryAreaStore("area-1")])
    with pytest.raises(KeyError, match="unknown area"):
        fab.kill_area("area-9")


def test_status_reports_each_area():
    fab = default_fabric(3)
    fab.write("x", {"v": 1})
    st = fab.status()
    assert [s["name"] for s in st] == ["area-1", "area-2", "area-3"]
    assert all(s["healthy"] for s in st)
    assert all(s["count"] == 1 for s in st)
