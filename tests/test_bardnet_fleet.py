"""Tier 1 — hermetic real-roster onboard + ping-fan-out test (PLAN_bardnet_fleet_test, T1.2).

The real fleet roster (``tests/fleet_roster.py``) drives the *built* bardnet flow,
fully in-process: the real Registry + Router apps share one ``DeviceStore`` +
``ChannelStore`` (a device the Registry admits via invite-redeem is instantly a
member the Router's ping gate can see), driven through the real endpoints —
``POST /channels`` / ``POST /invites`` / ``POST /invites/{token}/redeem`` (onboard),
``GET /channels/{id}/members`` (roster), the ``/v1/agent-link`` receive-link, and
``POST /channels/{id}/ping`` (fan-out).

This parametrizes the frozen ping contract (``tests/test_box_ping.py``) with the
actual fleet: all six devices onboard in succession; every device with a live link
receives ``box.ping``; the deliberately-unreachable boxes (``beagle``/``barney``)
are reported ``offline`` — a clean 200, not an error.

Hermetic per CLAUDE.md §11: in-process ``TestClient`` (no sockets), deterministic
device keypairs from ``tests/fakes``, and per-run ephemeral secrets (never
hardcoded, per §0.2).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import secrets

import jwt
from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from registry.app import create_app as create_registry
from registry.channel_store import ChannelStore
from registry.device_store import DeviceStore
from registry.store import RegistryStore
from router.app import create_app as create_router
from router.broker import BrokerLinkManager
from tests.fakes.ed25519_helper import keypair_for, mint_device_token
from tests.fakes.jwt_helper import TEST_ISSUER
from tests.fleet_roster import FLEET_ROSTER
from tests.test_router import FakeAgentClient, FakeRegistryClient

# Per-run ephemeral secrets — generated, never hardcoded (coding-rules §0.2), the
# same pattern scripts/smoke_box_demo.py uses.
FLEET_SECRET = secrets.token_urlsafe(32)
JOIN_SECRET = secrets.token_urlsafe(32)
INVITE_SECRET = secrets.token_urlsafe(32)
INVITE_BASE_URL = "https://join.bardllm.dev/i"

CHANNEL_ID = "box-fleet"
OTHER_CHANNEL_ID = "box-other"


class _Fabric:
    """The in-process bardnet fabric: shared stores wired into both apps."""

    def __init__(self) -> None:
        # ``None`` paths keep the stores in-memory (hermetic, no temp files).
        self.devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=TEST_ISSUER)
        self.channels = ChannelStore(
            self.devices,
            None,
            invite_secret=INVITE_SECRET,
            issuer=TEST_ISSUER,
            invite_base_url=INVITE_BASE_URL,
        )
        verifier = FleetOrDeviceVerifier(
            JwtVerifier(FLEET_SECRET, "HS256", TEST_ISSUER),
            PerDeviceVerifier(self.devices, issuer=TEST_ISSUER),
        )
        self.registry = TestClient(
            create_registry(
                RegistryStore(None),
                verifier,
                device_store=self.devices,
                channel_store=self.channels,
            )
        )
        self.router = TestClient(
            create_router(
                FakeRegistryClient(),
                FakeAgentClient(),
                verifier,
                broker=BrokerLinkManager(),
                channel_store=self.channels,
            )
        )
        self.fleet_auth = {"Authorization": f"Bearer {mint_fleet_token()}"}

    def create_box(self, channel_id: str) -> None:
        r = self.registry.post(
            "/channels",
            json={"channelId": channel_id, "label": channel_id},
            headers=self.fleet_auth,
        )
        assert r.status_code == 200, r.text

    def onboard(self, channel_id: str, device_id: str, label: str) -> int:
        """Run the real onboard rail: mint an invite, redeem it with the device's
        on-device public key. Returns the redeem status code."""
        inv = self.registry.post(
            "/invites", json={"channelId": channel_id}, headers=self.fleet_auth
        )
        token = inv.json()["inviteToken"]
        _, public_key = keypair_for(device_id)
        red = self.registry.post(
            f"/invites/{token}/redeem",
            json={"deviceId": device_id, "publicKey": public_key, "label": label},
        )
        return red.status_code

    def onboard_all(self, channel_id: str) -> None:
        for dev in FLEET_ROSTER:
            assert self.onboard(channel_id, dev.device_id, dev.label) == 200

    def members(self, channel_id: str) -> list[str]:
        r = self.registry.get(f"/channels/{channel_id}/members", headers=self.fleet_auth)
        assert r.status_code == 200, r.text
        return r.json()["deviceIds"]

    def device_auth(self, device_id: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {_device_token(device_id)}"}

    def open_link(self, stack: contextlib.ExitStack, device_id: str):
        ws = stack.enter_context(self.router.websocket_connect("/v1/agent-link"))
        ws.send_json({"type": "hello", "agentId": device_id, "authToken": _device_token(device_id)})
        assert ws.receive_json() == {"type": "hello_ok"}
        return ws


def mint_fleet_token() -> str:
    """A fleet/admin HMAC token — creates the box + mints invites (never a member)."""
    now = _dt.datetime.now(_dt.UTC)
    return jwt.encode(
        {"sub": "bard-admin", "iss": TEST_ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        FLEET_SECRET,
        algorithm="HS256",
    )


def _device_token(device_id: str) -> str:
    private_key, _ = keypair_for(device_id)
    return mint_device_token(device_id, private_key, issuer=TEST_ISSUER, ttl_s=3600)


def test_onboard_all_devices_in_succession():
    """Every roster device redeems an invite and lands ACTIVE in the box, in
    roster order (membership is an ordered append of the redeem sequence)."""
    fabric = _Fabric()
    fabric.create_box(CHANNEL_ID)
    for dev in FLEET_ROSTER:
        assert fabric.onboard(CHANNEL_ID, dev.device_id, dev.label) == 200
    assert fabric.members(CHANNEL_ID) == [dev.device_id for dev in FLEET_ROSTER]


def test_ping_fans_out_to_all_online():
    """Every device holds a live receive-link; one member pings; the box.ping
    fans out to every OTHER member and `delivered` == roster \\ {sender}."""
    fabric = _Fabric()
    fabric.create_box(CHANNEL_ID)
    fabric.onboard_all(CHANNEL_ID)
    sender = FLEET_ROSTER[0].device_id
    with contextlib.ExitStack() as stack:
        sockets = {dev.device_id: fabric.open_link(stack, dev.device_id) for dev in FLEET_ROSTER}
        resp = fabric.router.post(
            f"/channels/{CHANNEL_ID}/ping", headers=fabric.device_auth(sender)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        expected = sorted(dev.device_id for dev in FLEET_ROSTER if dev.device_id != sender)
        assert sorted(body["delivered"]) == expected
        assert body["offline"] == []
        for dev in FLEET_ROSTER:
            if dev.device_id == sender:
                continue
            frame = sockets[dev.device_id].receive_json()
            assert frame["type"] == "box.ping"
            assert frame["from"] == sender
            assert frame["channelId"] == CHANNEL_ID


def test_offline_boxes_listed_not_errored():
    """The deliberately-unreachable boxes (beagle, barney) hold no link: the ping
    still succeeds (200), they are listed `offline`, the rest `delivered`."""
    fabric = _Fabric()
    fabric.create_box(CHANNEL_ID)
    fabric.onboard_all(CHANNEL_ID)
    online = [dev for dev in FLEET_ROSTER if dev.reachable_default]
    offline = [dev for dev in FLEET_ROSTER if not dev.reachable_default]
    sender = "dev-mac"
    with contextlib.ExitStack() as stack:
        sockets = {dev.device_id: fabric.open_link(stack, dev.device_id) for dev in online}
        resp = fabric.router.post(
            f"/channels/{CHANNEL_ID}/ping", headers=fabric.device_auth(sender)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert sorted(body["offline"]) == sorted(dev.device_id for dev in offline)
        assert sorted(body["delivered"]) == sorted(
            dev.device_id for dev in online if dev.device_id != sender
        )
        for dev in online:
            if dev.device_id == sender:
                continue
            assert sockets[dev.device_id].receive_json()["type"] == "box.ping"


def test_ping_before_onboard_is_403():
    """A roster device that has NOT redeemed into the box cannot ping it. Here the
    holdout has a valid identity (redeemed into a different box) but is not a member
    of the shared box, so the ping is forbidden (403), not unauthorized (401)."""
    fabric = _Fabric()
    fabric.create_box(CHANNEL_ID)
    holdout = FLEET_ROSTER[-1].device_id
    for dev in FLEET_ROSTER:
        if dev.device_id == holdout:
            continue
        assert fabric.onboard(CHANNEL_ID, dev.device_id, dev.label) == 200
    # Give the holdout a real identity by onboarding it into a SEPARATE box.
    fabric.create_box(OTHER_CHANNEL_ID)
    assert fabric.onboard(OTHER_CHANNEL_ID, holdout, holdout) == 200
    resp = fabric.router.post(f"/channels/{CHANNEL_ID}/ping", headers=fabric.device_auth(holdout))
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden"
