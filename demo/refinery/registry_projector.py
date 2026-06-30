"""Registry projector — self-registers every refinery element into the REAL
bard-infra Registry as an agent (self-discovery), then heartbeats to keep liveness.

This is the demo's headline: a refinery element *is* a bard-infra agent. We reuse the
real Registry contract verbatim (see bard-infra ``agent/register.py`` /
``registry/app.py``): ``POST /register`` with a bearer HS256 JWT, body
``{agentId, address, capabilities, powerProfile}`` — no Registry code change. Refinery
semantics ride in the free-form ``agentId`` + ``capabilities`` tags because the
Registry's ``RegistrationBody``/``PowerProfile`` schemas forbid extra fields.

Discovery + liveness only: the Registry carries identity/classification and heartbeat
staleness (online/offline). Live process telemetry stays in the orchestrator (PLAN §4).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import jwt

from refinery.model import Element

MIN_SECRET_BYTES = 32  # RFC 7518 §3.2, matches bard-infra BARDPRO_JWT_SECRET


class ProjectorConfigError(RuntimeError):
    """Raised on invalid/missing projector configuration (fail-fast, §11)."""


@dataclass(frozen=True)
class ProjectorConfig:
    registry_url: str = "http://127.0.0.1:8081"
    jwt_secret: str = ""
    jwt_issuer: str = "bardllm-pro"
    jwt_subject: str = "refinery-fleet"
    heartbeat_seconds: float = 15.0
    token_ttl_seconds: int = 3600

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ProjectorConfig:
        env = os.environ if env is None else env
        secret = env.get("REFINERY_JWT_SECRET", "")
        if len(secret.encode()) < MIN_SECRET_BYTES:
            raise ProjectorConfigError(
                "REFINERY_JWT_SECRET must be >= 32 bytes (set it via env / Secret "
                "Manager; never commit a real value to this public repo)"
            )
        return cls(
            registry_url=env.get("REFINERY_REGISTRY_URL", cls.registry_url),
            jwt_secret=secret,
            jwt_issuer=env.get("REFINERY_JWT_ISSUER", cls.jwt_issuer),
            heartbeat_seconds=float(env.get("REFINERY_HEARTBEAT_SECONDS", "15")),
        )


def registration_body(element: Element) -> dict:
    """The exact ``/register`` body for one element (Registry-contract shaped)."""
    return {
        "agentId": element.agent_id,
        "address": f"refinery://{element.section_id}/{element.tag}",
        "capabilities": element.capabilities,
        "powerProfile": {"name": f"{element.type}:{element.section_id}"},
    }


class RegistryProjector:
    """Projects refinery elements into the real bard-infra Registry."""

    def __init__(self, config: ProjectorConfig) -> None:
        self.config = config

    def mint_token(self, *, now: datetime | None = None) -> str:
        """One shared fleet JWT (HS256) — any valid fleet token may register any agent."""
        now = now or datetime.now(UTC)
        claims = {
            "sub": self.config.jwt_subject,
            "iss": self.config.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(seconds=self.config.token_ttl_seconds),
        }
        return jwt.encode(claims, self.config.jwt_secret, algorithm="HS256")

    async def register(
        self, client: httpx.AsyncClient, element: Element, token: str
    ) -> httpx.Response:
        resp = await client.post(
            f"{self.config.registry_url}/register",
            json=registration_body(element),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp

    async def register_all(
        self, client: httpx.AsyncClient, elements: Iterable[Element], token: str
    ) -> int:
        count = 0
        for element in elements:
            await self.register(client, element, token)
            count += 1
        return count

    async def heartbeat_loop(
        self,
        client: httpx.AsyncClient,
        elements: Iterable[Element],
        stop: asyncio.Event,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Re-register every element each interval until ``stop`` is set.

        Re-registration *is* the heartbeat (the Registry has no separate endpoint);
        the token is re-minted each round so it never expires mid-run.
        """
        elements = list(elements)
        while not stop.is_set():
            token = self.mint_token()
            await self.register_all(client, elements, token)
            await sleep(self.config.heartbeat_seconds)
