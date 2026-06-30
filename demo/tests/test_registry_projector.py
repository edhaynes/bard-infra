"""Tests for the Registry projector — full coverage, no real network (respx mocks)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import jwt
import pytest
import respx
from refinery.model import Element
from refinery.registry_projector import (
    ProjectorConfig,
    ProjectorConfigError,
    RegistryProjector,
    registration_body,
)

SECRET = "x" * 32  # >= 32 bytes
REG = "http://reg.test:8081"


def _el(tag="PT-101", etype="sensor") -> Element:
    return Element(
        type=etype,
        tag=tag,
        signal="pressure",
        unit="bar",
        normal=(1.0, 2.0),
        section_id="S1",
        unit_id="U-110",
    )


def _cfg() -> ProjectorConfig:
    return ProjectorConfig(registry_url=REG, jwt_secret=SECRET)


# ---------------------------------------------------------------- config


def test_from_env_valid_and_custom():
    cfg = ProjectorConfig.from_env(
        {
            "REFINERY_JWT_SECRET": SECRET,
            "REFINERY_REGISTRY_URL": REG,
            "REFINERY_JWT_ISSUER": "custom-iss",
            "REFINERY_HEARTBEAT_SECONDS": "3",
        }
    )
    assert cfg.registry_url == REG
    assert cfg.jwt_issuer == "custom-iss"
    assert cfg.heartbeat_seconds == 3.0


def test_from_env_missing_secret_fails_fast():
    with pytest.raises(ProjectorConfigError, match=">= 32 bytes"):
        ProjectorConfig.from_env({})


def test_from_env_short_secret_fails_fast():
    with pytest.raises(ProjectorConfigError, match=">= 32 bytes"):
        ProjectorConfig.from_env(
            {"REFINERY_JWT_SECRET": "tooshort"}  # pragma: allowlist secret
        )


def test_from_env_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv("REFINERY_JWT_SECRET", SECRET)
    monkeypatch.delenv("REFINERY_REGISTRY_URL", raising=False)
    cfg = ProjectorConfig.from_env()
    assert cfg.registry_url == "http://127.0.0.1:8081"  # default
    assert cfg.jwt_secret == SECRET


# ---------------------------------------------------------------- body + token


def test_registration_body_shape():
    body = registration_body(_el())
    assert body["agentId"] == "sensor.S1.PT-101"
    assert body["address"] == "refinery://S1/PT-101"
    assert "type:sensor" in body["capabilities"]
    assert body["powerProfile"] == {"name": "sensor:S1"}
    # only the four Registry-permitted keys (RegistrationBody forbids extras)
    assert set(body) == {"agentId", "address", "capabilities", "powerProfile"}


def test_mint_token_claims_with_fixed_now():
    proj = RegistryProjector(_cfg())
    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    token = proj.mint_token(now=now)
    # assert claim *values*, not liveness — pin disables time checks
    decoded = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert decoded["sub"] == "refinery-fleet"
    assert decoded["iss"] == "bardllm-pro"
    assert decoded["exp"] - decoded["iat"] == 3600


def test_mint_token_default_now():
    proj = RegistryProjector(_cfg())
    token = proj.mint_token()
    decoded = jwt.decode(token, SECRET, algorithms=["HS256"], issuer="bardllm-pro")
    assert decoded["sub"] == "refinery-fleet"


# ---------------------------------------------------------------- register


@respx.mock
async def test_register_success_sends_bearer_and_body():
    route = respx.post(f"{REG}/register").mock(
        return_value=httpx.Response(200, json={"status": "active"})
    )
    proj = RegistryProjector(_cfg())
    token = proj.mint_token()
    async with httpx.AsyncClient() as client:
        resp = await proj.register(client, _el(), token)
    assert resp.status_code == 200
    req = route.calls.last.request
    assert req.headers["Authorization"] == f"Bearer {token}"
    assert b"sensor.S1.PT-101" in req.content


@respx.mock
async def test_register_raises_on_http_error():
    respx.post(f"{REG}/register").mock(return_value=httpx.Response(401))
    proj = RegistryProjector(_cfg())
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await proj.register(client, _el(), proj.mint_token())


@respx.mock
async def test_register_all_counts_every_element():
    respx.post(f"{REG}/register").mock(return_value=httpx.Response(200, json={}))
    proj = RegistryProjector(_cfg())
    elements = [_el(tag=f"PT-{i}") for i in range(5)]
    async with httpx.AsyncClient() as client:
        n = await proj.register_all(client, elements, proj.mint_token())
    assert n == 5


# ---------------------------------------------------------------- heartbeat


@respx.mock
async def test_heartbeat_loop_registers_then_stops():
    route = respx.post(f"{REG}/register").mock(return_value=httpx.Response(200, json={}))
    proj = RegistryProjector(_cfg())
    elements = [_el(tag="A"), _el(tag="B")]
    stop = asyncio.Event()
    sleeps: list[float] = []

    async def fake_sleep(secs: float) -> None:
        sleeps.append(secs)
        stop.set()  # break the loop after the first round

    await proj.heartbeat_loop(client_factory(), elements, stop, sleep=fake_sleep)
    assert route.call_count == 2  # one per element, one round
    assert sleeps == [15.0]  # slept once at the configured interval


def client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient()
