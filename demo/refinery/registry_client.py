"""Read-side client for the real bard-infra Registry.

The orchestrator uses this to pull the live fleet (`GET /agents`) so the console can show
**real** discovery + liveness (active/stale) instead of the sim. It reuses the projector's
HS256 token mint. If the Registry isn't configured (no `REFINERY_JWT_SECRET`), the
orchestrator runs sim-only — :meth:`RegistryReader.from_env` returns ``None`` and the
console reports the Registry as disconnected (fail-soft, never a crash).
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from refinery.registry_projector import (
    ProjectorConfig,
    ProjectorConfigError,
    RegistryProjector,
)


class RegistryReader:
    """Synchronous reader for the Registry's bearer-gated ``/agents`` endpoint."""

    def __init__(self, projector: RegistryProjector, *, timeout: float = 2.0) -> None:
        self.projector = projector
        self._timeout = timeout

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RegistryReader | None:
        """Build from env, or ``None`` when no fleet secret is set (sim-only mode)."""
        try:
            config = ProjectorConfig.from_env(env)
        except ProjectorConfigError:
            return None
        return cls(RegistryProjector(config))

    @property
    def url(self) -> str:
        return self.projector.config.registry_url

    def agents(self) -> list[dict]:
        """Live agent records: ``[{agentId, status: active|stale, capabilities, ...}]``."""
        token = self.projector.mint_token()
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self.url}/agents", headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.json()
