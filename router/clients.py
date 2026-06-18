"""Outbound clients the Router uses to reach the Registry and Agents.

Both are protocols so tests inject in-process fakes and the real HTTP clients
stay swappable (CLAUDE.md §2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import httpx

from common.protocol import Request, Response

if TYPE_CHECKING:
    from common.config import Config


class AgentNotFound(Exception):
    """targetAgent is not in the registry (maps to 404)."""


class AgentUnavailable(Exception):
    """Registry or agent is unreachable / errored (maps to 502)."""


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class RegistryClient(Protocol):
    def lookup(self, agent_id: str, token: str) -> str:
        """Return the agent's address, or raise AgentNotFound / AgentUnavailable."""
        ...

    def register(self, body: dict, token: str) -> dict:
        """Relay an agent registration to the Registry's /register on the
        agent's behalf (slice 2 / ADR-0013 single front door).

        ``body`` is the AgentRegistration payload (agentId already bound to the
        link's authenticated identity by the caller). Returns the AgentRecord;
        raises AgentUnavailable on transport/HTTP error.
        """
        ...


class AgentClient(Protocol):
    def infer(self, address: str, request: Request, token: str) -> Response:
        """Forward to the agent and return its Response, or raise AgentUnavailable."""
        ...


class HttpRegistryClient:
    def __init__(self, base_url: str, *, verify: bool | str = True, timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        self._verify = verify
        self._timeout = timeout

    @classmethod
    def from_config(
        cls, config: Config, *, verify: bool | str = True, timeout: float = 30.0
    ) -> HttpRegistryClient:
        """Build the registry base URL from ``config.registry_scheme`` (bug #60).

        The agent already honors the configured scheme (``agent/register.py``);
        the router must too, else an http registry is dialed over https and the
        lookup fails. ``registry_scheme`` defaults to ``https``, so the full-TLS
        path is unchanged; ``http`` is gated by ``allow_insecure_http`` in
        ``load_config`` (fails fast otherwise).
        """
        base = f"{config.registry_scheme}://{config.registry_host}:{config.registry_port}"
        return cls(base, verify=verify, timeout=timeout)

    def lookup(self, agent_id: str, token: str) -> str:
        try:
            resp = httpx.get(
                f"{self._base}/agents/{agent_id}",
                headers=_bearer(token),
                verify=self._verify,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"registry unreachable: {exc}") from exc
        if resp.status_code == 404:
            raise AgentNotFound(agent_id)
        if resp.status_code >= 400:
            raise AgentUnavailable(f"registry error {resp.status_code}")
        return resp.json()["address"]

    def register(self, body: dict, token: str) -> dict:
        try:
            resp = httpx.post(
                f"{self._base}/register",
                json=body,
                headers=_bearer(token),
                verify=self._verify,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"registry unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise AgentUnavailable(f"registry register failed {resp.status_code}")
        return resp.json()


class HttpAgentClient:
    def __init__(self, *, verify: bool | str = True, timeout: float = 30.0):
        self._verify = verify
        self._timeout = timeout

    def infer(self, address: str, request: Request, token: str) -> Response:
        url = address if address.startswith("http") else f"https://{address}"
        try:
            resp = httpx.post(
                f"{url}/infer",
                json=request.model_dump(exclude_none=True),
                headers=_bearer(token),
                verify=self._verify,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"agent unreachable: {exc}") from exc
        if resp.status_code >= 500:
            raise AgentUnavailable(f"agent error {resp.status_code}")
        if resp.status_code >= 400:
            raise AgentUnavailable(f"agent rejected request: {resp.status_code}")
        return Response.model_validate(resp.json())
