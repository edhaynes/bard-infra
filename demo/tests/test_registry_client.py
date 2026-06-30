"""Tests for the Registry read client — full coverage, Registry mocked (respx)."""

from __future__ import annotations

import httpx
import respx
from refinery.registry_client import RegistryReader

SECRET = "y" * 32
REG = "http://reg.test:8081"


def test_from_env_none_without_secret():
    assert RegistryReader.from_env({}) is None


def test_from_env_builds_reader_and_url():
    reader = RegistryReader.from_env({"REFINERY_JWT_SECRET": SECRET, "REFINERY_REGISTRY_URL": REG})
    assert reader is not None
    assert reader.url == REG


@respx.mock
def test_agents_reads_registry():
    respx.get(f"{REG}/agents").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"agentId": "sensor.S1.PT-1101", "status": "active", "capabilities": []},
                {"agentId": "valve.S1.FV-1104", "status": "stale", "capabilities": []},
            ],
        )
    )
    reader = RegistryReader.from_env({"REFINERY_JWT_SECRET": SECRET, "REFINERY_REGISTRY_URL": REG})
    agents = reader.agents()
    assert {a["agentId"] for a in agents} == {"sensor.S1.PT-1101", "valve.S1.FV-1104"}
    # the request carried a bearer token
    req = respx.calls.last.request
    assert req.headers["Authorization"].startswith("Bearer ")
