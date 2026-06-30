"""Distributed fabric — replicated device-state store with failover + digital twin.

The bard-infra distributed design (DESIGN_industrial_fabric.md): each device's
microcontroller reports its state up through industrial ARM gateways into a shared
state store that is **replicated across separate areas**. Writes go to every healthy
area; reads fail over to the next healthy area. Because the store keeps the last write,
a device that dies leaves its last-known state behind — its **digital twin**.

Backends are swappable behind :class:`AreaStore` (coding-rules §3): an in-memory store
(default / tests, no network) and a Valkey-backed store (the open Redis fork) for the
faithful live demo. Replication/failover logic lives in :class:`ReplicatedFabric` and is
identical across backends.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Protocol


class AreaStore(ABC):
    """One replication area (a single store instance)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._healthy = True

    @property
    def healthy(self) -> bool:
        return self._healthy

    def set_healthy(self, value: bool) -> None:
        self._healthy = value

    @abstractmethod
    def write(self, tag: str, payload: dict) -> None: ...

    @abstractmethod
    def read(self, tag: str) -> dict | None: ...

    @abstractmethod
    def count(self) -> int: ...


class InMemoryAreaStore(AreaStore):
    """Dict-backed area (default + unit tests)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._data: dict[str, dict] = {}

    def write(self, tag: str, payload: dict) -> None:
        self._data[tag] = dict(payload)

    def read(self, tag: str) -> dict | None:
        v = self._data.get(tag)
        return dict(v) if v is not None else None

    def count(self) -> int:
        return len(self._data)


class ValkeyClient(Protocol):
    """The slice of the valkey-py / redis-py client this store uses."""

    def set(self, name: str, value: str) -> Any: ...
    def get(self, name: str) -> Any: ...
    def keys(self, pattern: str) -> Any: ...


class ValkeyAreaStore(AreaStore):
    """Valkey-backed area (BSD-3 open Redis fork). Client is injected (§3)."""

    def __init__(self, name: str, client: ValkeyClient, *, prefix: str = "twin:") -> None:
        super().__init__(name)
        self._client = client
        self._prefix = prefix

    def write(self, tag: str, payload: dict) -> None:
        self._client.set(self._prefix + tag, json.dumps(payload))

    def read(self, tag: str) -> dict | None:
        raw = self._client.get(self._prefix + tag)
        if raw is None:
            return None
        return json.loads(raw.decode() if isinstance(raw, bytes) else raw)

    def count(self) -> int:
        return len(list(self._client.keys(self._prefix + "*")))


class ReplicatedFabric:
    """Writes to every healthy area; reads fail over; serves digital twins."""

    def __init__(self, areas: list[AreaStore]) -> None:
        if not areas:
            raise ValueError("ReplicatedFabric needs at least one area")
        self.areas = areas

    def write(self, tag: str, payload: dict) -> int:
        """Replicate a device-state write to all healthy areas; returns #written."""
        written = 0
        for area in self.areas:
            if area.healthy:
                area.write(tag, payload)
                written += 1
        return written

    def read(self, tag: str) -> dict | None:
        """Read a device's last state, failing over to the next healthy area."""
        for area in self.areas:
            if not area.healthy:
                continue
            value = area.read(tag)
            if value is not None:
                return {**value, "served_by": area.name}
        return None

    def twin(self, tag: str) -> dict | None:
        """The digital twin = last persisted state (survives the device's death)."""
        return self.read(tag)

    def _find(self, name: str) -> AreaStore:
        for area in self.areas:
            if area.name == name:
                return area
        raise KeyError(f"unknown area '{name}'")

    def kill_area(self, name: str) -> None:
        self._find(name).set_healthy(False)

    def restore_area(self, name: str) -> None:
        self._find(name).set_healthy(True)

    def status(self) -> list[dict]:
        return [{"name": a.name, "healthy": a.healthy, "count": a.count()} for a in self.areas]


def default_fabric(n_areas: int = 3) -> ReplicatedFabric:
    """In-memory replicated fabric (the default; swap to Valkey via a factory)."""
    return ReplicatedFabric([InMemoryAreaStore(f"area-{i + 1}") for i in range(n_areas)])
