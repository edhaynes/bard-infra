"""In-memory FakeRegistry implementing registry.openapi.yaml semantics.

Lets Lane A (Router) develop against the registry contract without Lane B's
real service. No persistence, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AgentNotFound(KeyError):
    """Raised when an unknown agentId is looked up (maps to 404)."""


@dataclass
class FakeRegistry:
    _agents: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register(self, agent_id: str, address: str, **extra: Any) -> dict[str, Any]:
        record = {"agentId": agent_id, "address": address, **extra}
        self._agents[agent_id] = record
        return record

    def get(self, agent_id: str) -> dict[str, Any]:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFound(agent_id) from exc

    def list(self) -> list[dict[str, Any]]:
        return list(self._agents.values())
