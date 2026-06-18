"""Lane A unit tests — router logic against in-process fake clients."""

from __future__ import annotations

import datetime as _dt

import jwt
import pytest
from fastapi.testclient import TestClient

from common.auth import AuthError, FleetTokenMinter, JwtVerifier
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from common.protocol import Request, Response, ResponseMetadata
from registry.device_store import DeviceStore
from router.app import create_app
from router.clients import AgentNotFound, AgentUnavailable
from tests.fakes.jwt_helper import TEST_ISSUER, TEST_JWT_SECRET, mint_test_token


class FakeRegistryClient:
    def __init__(self, address: str | None = "agent-1.local:8444"):
        self._address = address

    def lookup(self, agent_id: str, token: str) -> str:
        if self._address is None:
            raise AgentNotFound(agent_id)
        return self._address


class FakeAgentClient:
    def __init__(self, *, fail: bool = False):
        self._fail = fail

    def infer(self, address: str, request: Request, token: str) -> Response:
        if self._fail:
            raise AgentUnavailable("boom")
        return Response(
            id=request.id,
            type="text",
            content=f"echo: {request.content}",
            metadata=ResponseMetadata(agentId="agent-1"),
        )


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _client(registry=None, agent=None) -> TestClient:
    return TestClient(
        create_app(registry or FakeRegistryClient(), agent or FakeAgentClient(), _verifier())
    )


def _req(token: str, msg_type: str = "text", target: str = "agent-1") -> dict:
    return {
        "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        "type": msg_type,
        "content": "hi",
        "metadata": {"targetAgent": target, "authToken": token},
    }


def test_message_round_trip():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = _client().post("/v1/message", json=_req(token))
    assert r.status_code == 200 and r.json()["content"] == "echo: hi"


def test_message_bad_token_401():
    r = _client().post("/v1/message", json=_req("nope"))
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"


def test_message_voice_501():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = _client().post("/v1/message", json=_req(token, msg_type="voice"))
    assert r.status_code == 501 and r.json()["error"] == "unsupported_type"


def test_message_unknown_agent_404():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = _client(registry=FakeRegistryClient(address=None)).post("/v1/message", json=_req(token))
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_message_agent_unavailable_502():
    token = mint_test_token(secret=TEST_JWT_SECRET)
    r = _client(agent=FakeAgentClient(fail=True)).post("/v1/message", json=_req(token))
    assert r.status_code == 502 and r.json()["error"] == "agent_unavailable"
    assert r.json()["retry"] is True


# --------------------------------------------------------------------------- #
# Bug #63 — per-device caller must reach the data path.
#
# The Registry gates /agents fleet-only. A per-device caller is accepted at
# /v1/message (FleetOrDeviceVerifier) but the internal registry lookup must NOT
# forward the caller's per-device token (the Registry would 401 -> 502). With a
# FleetTokenMinter wired as ``service_tokens`` the Router authenticates that hop
# as the fleet, so the per-device caller reaches the agent (200).
# --------------------------------------------------------------------------- #


class FleetGatedRegistryClient:
    """Fake Registry that, like the real one, accepts ONLY a fleet token on its
    lookup. A per-device token (signed with a device secret, not the fleet
    secret) fails verification and surfaces as AgentUnavailable — exactly the
    502 a redeemed device hit before the fix."""

    def __init__(self, address: str = "agent-1.local:8444"):
        self._address = address
        self._fleet = JwtVerifier(TEST_JWT_SECRET, "HS256", TEST_ISSUER)

    def lookup(self, agent_id: str, token: str) -> str:
        try:
            self._fleet.verify(token)
        except AuthError as exc:
            raise AgentUnavailable(f"registry error 401: {exc}") from exc
        return self._address


def _active_device(tmp_path) -> tuple[DeviceStore, str, str]:
    """Enroll + approve one device; return (store, deviceId, deviceSecret)."""
    store = DeviceStore(
        tmp_path / "devices.json",
        join_token_secret="join-token-secret-padding-0123456789-abc",
        issuer=TEST_ISSUER,
    )
    join = store.issue_join_token(ttl_s=600)
    store.enroll("dev-a", join)
    _, secret = store.approve("dev-a")
    return store, "dev-a", secret


def _fleet_or_device_verifier(store: DeviceStore) -> FleetOrDeviceVerifier:
    return FleetOrDeviceVerifier(
        JwtVerifier(TEST_JWT_SECRET, "HS256", TEST_ISSUER),
        PerDeviceVerifier(store, issuer=TEST_ISSUER),
    )


def test_per_device_caller_reaches_data_path_with_service_token(tmp_path):
    """Regression for bug #63: a per-device token authorizes /v1/message and the
    Router's OWN fleet service token authorizes the registry lookup -> 200."""
    store, device_id, secret = _active_device(tmp_path)
    device_token = store.mint_device_token(device_id, secret, ttl_s=3600)

    app = create_app(
        FleetGatedRegistryClient(),
        FakeAgentClient(),
        _fleet_or_device_verifier(store),
        service_tokens=FleetTokenMinter(TEST_JWT_SECRET, issuer=TEST_ISSUER),
    )
    r = TestClient(app).post("/v1/message", json=_req(device_token))
    assert r.status_code == 200 and r.json()["content"] == "echo: hi"


def test_per_device_caller_502_without_service_token(tmp_path):
    """Pins the bug: with no service-token minter the caller's per-device token
    is forwarded to the fleet-only registry lookup -> AgentUnavailable -> 502.
    This is the pre-fix behavior the service token corrects."""
    store, device_id, secret = _active_device(tmp_path)
    device_token = store.mint_device_token(device_id, secret, ttl_s=3600)

    app = create_app(
        FleetGatedRegistryClient(),
        FakeAgentClient(),
        _fleet_or_device_verifier(store),
        # service_tokens omitted -> caller token forwarded (v1 behavior).
    )
    r = TestClient(app).post("/v1/message", json=_req(device_token))
    assert r.status_code == 502 and r.json()["error"] == "agent_unavailable"


def test_fleet_caller_unaffected_by_service_token(tmp_path):
    """A legacy fleet caller still round-trips with a service-token minter wired
    — the change is additive, not a regression for the fleet path."""
    store, _, _ = _active_device(tmp_path)
    fleet_token = mint_test_token(secret=TEST_JWT_SECRET)
    app = create_app(
        FleetGatedRegistryClient(),
        FakeAgentClient(),
        _fleet_or_device_verifier(store),
        service_tokens=FleetTokenMinter(TEST_JWT_SECRET, issuer=TEST_ISSUER),
    )
    r = TestClient(app).post("/v1/message", json=_req(fleet_token))
    assert r.status_code == 200 and r.json()["content"] == "echo: hi"


# --------------------------------------------------------------------------- #
# FleetTokenMinter (common/auth.py) — the hop changed for bug #63.
# --------------------------------------------------------------------------- #


def test_fleet_token_minter_mints_fleet_verifiable_token():
    minter = FleetTokenMinter(TEST_JWT_SECRET, issuer=TEST_ISSUER, subject="bard-router")
    claims = JwtVerifier(TEST_JWT_SECRET, "HS256", TEST_ISSUER).verify(minter.token())
    assert claims["sub"] == "bard-router"
    assert claims["iss"] == TEST_ISSUER


def test_fleet_token_minter_from_config():
    from common.config import Config

    cfg = Config(jwt_secret="s" * 32, jwt_issuer="bardllm-pro")
    minter = FleetTokenMinter.from_config(cfg, subject="svc")
    claims = JwtVerifier("s" * 32, "HS256", "bardllm-pro").verify(minter.token())
    assert claims["sub"] == "svc"


def test_fleet_token_minter_honors_injected_clock_for_expiry():
    fixed = _dt.datetime(2026, 6, 15, 12, 0, 0, tzinfo=_dt.UTC)
    minter = FleetTokenMinter(TEST_JWT_SECRET, issuer=TEST_ISSUER, ttl_s=120, clock=lambda: fixed)
    # Decode without exp validation: the fixed clock is in the past relative to
    # real now, so the point under test is the exp VALUE, not its validity.
    claims = jwt.decode(
        minter.token(),
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        issuer=TEST_ISSUER,
        options={"verify_exp": False},
    )
    assert claims["exp"] == int((fixed + _dt.timedelta(seconds=120)).timestamp())


def test_fleet_token_minter_no_issuer_omits_iss():
    minter = FleetTokenMinter(TEST_JWT_SECRET, issuer=None)
    claims = jwt.decode(
        minter.token(), TEST_JWT_SECRET, algorithms=["HS256"], options={"verify_iss": False}
    )
    assert "iss" not in claims


def test_fleet_token_minter_rejects_empty_secret():
    with pytest.raises(ValueError, match="JWT secret is required"):
        FleetTokenMinter("")
