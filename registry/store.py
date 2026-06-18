"""In-memory agent registry with JSON-file persistence (MVP).

HA / distributed KV is deferred (DESIGN.md §2). Persistence is a single JSON
file written on each mutation and loaded on construction.

Liveness (feature #54): every successful ``register`` stamps a server-side
``lastSeen``; an agent whose ``lastSeen`` is older than ``ttl_s`` is reported
``stale`` and excluded from placement (``/pool``, ``/schedule``) but kept in
the store for observability — stale records are never hard-deleted. The clock
is injectable so tests never sleep.
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common.power import PowerProfile, aggregate_pool

#: Default staleness TTL, seconds. Keep in sync with ``Config.agent_ttl_s``.
DEFAULT_TTL_S = 45.0

STATUS_ACTIVE = "active"
STATUS_STALE = "stale"


class AgentNotFound(KeyError):
    """Raised when an unknown agentId is looked up (maps to 404)."""


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class RegistryStore:
    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        ttl_s: float = DEFAULT_TTL_S,
        clock: Callable[[], _dt.datetime] | None = None,
    ):
        self._path = Path(state_path) if state_path else None
        self._ttl_s = ttl_s
        self._clock = clock or _utcnow
        self._agents: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path and self._path.is_file():
            self._agents = json.loads(self._path.read_text(encoding="utf-8"))

    def save(self) -> None:
        if self._path:
            self._path.write_text(json.dumps(self._agents, indent=2), encoding="utf-8")

    def register(
        self,
        agent_id: str,
        address: str,
        capabilities: list[str] | None = None,
        power_profile: dict | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {"agentId": agent_id, "address": address}
        if capabilities:
            record["capabilities"] = capabilities
        # Validate the power profile against the contract; raises ValidationError.
        # Persist it so the fleet/pool views can surface advertised capacity.
        if power_profile is not None:
            PowerProfile.model_validate(power_profile)
            record["powerProfile"] = power_profile
        now_iso = self._clock().isoformat()
        previous = self._agents.get(agent_id)
        # First registration time survives heartbeat re-registrations; lastSeen
        # is refreshed on every successful /register (the heartbeat).
        record["registeredAt"] = previous["registeredAt"] if previous else now_iso
        record["lastSeen"] = now_iso
        self._agents[agent_id] = record
        self.save()
        return self._annotated(record)

    def _is_stale(self, record: dict[str, Any]) -> bool:
        # Records persisted before liveness shipped carry only registeredAt.
        raw = record.get("lastSeen") or record.get("registeredAt")
        if not raw:
            return True
        age = (self._clock() - _dt.datetime.fromisoformat(raw)).total_seconds()
        return age > self._ttl_s

    def _annotated(self, record: dict[str, Any]) -> dict[str, Any]:
        """Read-time copy with computed ``status`` — never persisted."""
        out = dict(record)
        out["status"] = STATUS_STALE if self._is_stale(record) else STATUS_ACTIVE
        return out

    def pool(self) -> dict[str, Any]:
        """Aggregate the *live* agents' power profiles into a pooled-capacity
        view (total CPUs, memory, GPU-capable nodes) for the demo dashboard."""
        live = self.list(include_stale=False)
        return aggregate_pool([a["powerProfile"] for a in live if "powerProfile" in a])

    def get(self, agent_id: str) -> dict[str, Any]:
        try:
            return self._annotated(self._agents[agent_id])
        except KeyError as exc:
            raise AgentNotFound(agent_id) from exc

    def list(self, *, include_stale: bool = True) -> list[dict[str, Any]]:
        records = [self._annotated(r) for r in self._agents.values()]
        if include_stale:
            return records
        return [r for r in records if r["status"] == STATUS_ACTIVE]
