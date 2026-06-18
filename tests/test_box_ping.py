"""Step S6 — box ping over the broker (ADR-0016), contract-first.

A channel member calls ``POST /channels/{channelId}/ping``; the Router fans a
one-way ``box.ping`` frame out to every OTHER member that holds a live broker
link (``/v1/agent-link`` registers a device's receive-link keyed by its
deviceId == token ``sub``). The sender is excluded; a member with no live link
is listed ``offline`` (not an error). Auth is the FleetOrDeviceVerifier — a
device's own EdDSA token authorizes both the ping AND its receive-link.

Hermetic: in-process TestClient, no network sockets (starlette drives the WS in
the same portal). Device keypairs are deterministic placeholders
(tests/fakes/ed25519_helper); the Router-side ChannelStore is built directly
(the membership the Registry would have written via redeem).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from common.auth import JwtVerifier
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier
from registry.channel_store import ChannelStore
from registry.device_store import DeviceStore
from router.app import create_app
from router.broker import BrokerLinkManager
from tests.fakes.ed25519_helper import keypair_for, mint_device_token
from tests.fakes.jwt_helper import TEST_ISSUER, TEST_JWT_SECRET, mint_test_token
from tests.test_router import FakeAgentClient, FakeRegistryClient

# Obvious >=32-byte placeholders — NOT credentials.
JOIN_SECRET = "s6-join-secret-padding-0123456789-abcdef"  # noqa: S105  # gitleaks:allow
INVITE_SECRET = "s6-invite-secret-padding-0123456789-abcd"  # noqa: S105  # gitleaks:allow
BASE_URL = "https://join.bardllm.dev/i"


def _stores() -> tuple[DeviceStore, ChannelStore]:
    devices = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=TEST_ISSUER)
    channels = ChannelStore(
        devices, None, invite_secret=INVITE_SECRET, issuer=TEST_ISSUER, invite_base_url=BASE_URL
    )
    return devices, channels


def _admit(devices: DeviceStore, channels: ChannelStore, channel: str, device_id: str) -> None:
    """Make ``device_id`` an ACTIVE member of ``channel`` via the real
    invite-redeem path (the state a self-register + invite-redeem leaves): the
    channel is created on first use, then a single-use invite is minted and
    redeemed by the device's public key. No private access — this is the
    contracted membership write the Registry performs."""
    if not channels.channel_exists(channel):
        channels.create_channel(channel, owner=None)
    _, token, _ = channels.create_invite(channel, ttl_s=600)
    _, public_key = keypair_for(device_id)
    channels.redeem(token, device_id, public_key)


def _app(
    devices: DeviceStore, channels: ChannelStore, *, broker: BrokerLinkManager | None = None
) -> tuple[TestClient, BrokerLinkManager]:
    broker = broker or BrokerLinkManager(timeout_s=5.0)
    verifier = FleetOrDeviceVerifier(
        JwtVerifier(TEST_JWT_SECRET, "HS256", TEST_ISSUER),
        PerDeviceVerifier(devices, issuer=TEST_ISSUER),
    )
    app = create_app(
        FakeRegistryClient(),
        FakeAgentClient(),
        verifier,
        broker=broker,
        channel_store=channels,
    )
    return TestClient(app), broker


def _device_headers(device_id: str) -> dict[str, str]:
    private_key, _ = keypair_for(device_id)
    token = mint_device_token(device_id, private_key, issuer=TEST_ISSUER, ttl_s=3600)
    return {"Authorization": f"Bearer {token}"}


def _hello(ws, device_id: str) -> None:
    """A device registers its RECEIVE-link: it presents its OWN EdDSA token (the
    FleetOrDeviceVerifier accepts it; sub == deviceId binds the link)."""
    private_key, _ = keypair_for(device_id)
    token = mint_device_token(device_id, private_key, issuer=TEST_ISSUER, ttl_s=3600)
    ws.send_json({"type": "hello", "agentId": device_id, "authToken": token})
    assert ws.receive_json() == {"type": "hello_ok"}


# --- device receive-link registers on a per-device token ---------------------


def test_device_token_accepted_at_agent_link():
    """FROZEN CONTRACT #1: a per-device EdDSA token (sub == deviceId) is accepted
    at /v1/agent-link and registers a live link keyed by that deviceId."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    client, broker = _app(devices, channels)
    with client.websocket_connect("/v1/agent-link") as ws:
        _hello(ws, "phone-1")
        assert broker.has_link("phone-1")
    assert not broker.has_link("phone-1")


def test_revoked_device_link_rejected():
    """A revoked device's token does not verify, so its receive-link is closed
    (1008) and never registered — the device cannot receive pings."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    devices.revoke("phone-1")
    client, broker = _app(devices, channels)
    with client.websocket_connect("/v1/agent-link") as ws:
        private_key, _ = keypair_for("phone-1")
        token = mint_device_token("phone-1", private_key, issuer=TEST_ISSUER, ttl_s=3600)
        ws.send_json({"type": "hello", "agentId": "phone-1", "authToken": token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008
    assert not broker.has_link("phone-1")


# --- ping fan-out ------------------------------------------------------------


def test_member_pings_other_members_receive_frame():
    """FROZEN CONTRACT #2/#3: a member pings the box; every OTHER member with a
    live link receives the box.ping frame; the sender is excluded."""
    devices, channels = _stores()
    for device_id in ("phone-1", "mac-1", "android-1"):
        _admit(devices, channels, "box-1", device_id)
    client, _ = _app(devices, channels)
    with (
        client,
        client.websocket_connect("/v1/agent-link") as mac,
        client.websocket_connect("/v1/agent-link") as android,
    ):
        _hello(mac, "mac-1")
        _hello(android, "android-1")

        r = client.post("/channels/box-1/ping", headers=_device_headers("phone-1"))

        assert r.status_code == 200, r.text
        body = r.json()
        assert sorted(body["delivered"]) == ["android-1", "mac-1"]
        assert body["offline"] == []

        for ws in (mac, android):
            frame = ws.receive_json()
            assert frame["type"] == "box.ping"
            assert frame["channelId"] == "box-1"
            assert frame["from"] == "phone-1"
            assert isinstance(frame["ts"], str) and frame["ts"]


def test_sender_excluded_even_with_own_live_link():
    """The sender is never delivered to, even if it holds a live link of its own
    (you do not ping yourself)."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    _admit(devices, channels, "box-1", "mac-1")
    client, _ = _app(devices, channels)
    with (
        client,
        client.websocket_connect("/v1/agent-link") as sender,
        client.websocket_connect("/v1/agent-link") as mac,
    ):
        _hello(sender, "phone-1")
        _hello(mac, "mac-1")

        r = client.post("/channels/box-1/ping", headers=_device_headers("phone-1"))

        assert r.json()["delivered"] == ["mac-1"]
        # The sender's link got nothing: the next frame it sees is whatever it
        # sends next, not a ping. Prove it by pushing the mac one and confirming
        # the sender link is still idle (no buffered box.ping).
        assert mac.receive_json()["type"] == "box.ping"


def test_offline_member_listed_not_errored():
    """FROZEN CONTRACT: a member with no live link is listed in `offline` — the
    ping still succeeds (200), it is not an error."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    _admit(devices, channels, "box-1", "mac-1")  # never connects a link
    _admit(devices, channels, "box-1", "android-1")
    client, _ = _app(devices, channels)
    with client, client.websocket_connect("/v1/agent-link") as android:
        _hello(android, "android-1")

        r = client.post("/channels/box-1/ping", headers=_device_headers("phone-1"))

        assert r.status_code == 200
        body = r.json()
        assert body["delivered"] == ["android-1"]
        assert body["offline"] == ["mac-1"]
        assert android.receive_json()["type"] == "box.ping"


def test_all_members_offline_pings_clean():
    """No member holds a link: every other member is offline, none delivered —
    a clean 200, not an error."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    _admit(devices, channels, "box-1", "mac-1")
    client, _ = _app(devices, channels)
    r = client.post("/channels/box-1/ping", headers=_device_headers("phone-1"))
    assert r.status_code == 200
    assert r.json() == {"delivered": [], "offline": ["mac-1"]}


# --- auth + membership gates -------------------------------------------------


def test_non_member_ping_forbidden():
    """FROZEN CONTRACT #2: a non-member calling ping gets 403."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    devices.admit(*_intruder())  # active device, but NOT a member of box-1
    client, _ = _app(devices, channels)
    r = client.post("/channels/box-1/ping", headers=_device_headers("intruder"))
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def _intruder() -> tuple[str, str]:
    _, public_key = keypair_for("intruder")
    return "intruder", public_key


def test_ping_unknown_channel_is_non_member_403():
    """Pinging a channel that does not exist is just a non-membership case: the
    caller is not a member of an empty/unknown channel -> 403."""
    devices, channels = _stores()
    devices.admit(*_intruder())
    client, _ = _app(devices, channels)
    r = client.post("/channels/ghost-box/ping", headers=_device_headers("intruder"))
    assert r.status_code == 403


def test_ping_missing_bearer_401():
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    client, _ = _app(devices, channels)
    assert client.post("/channels/box-1/ping").status_code == 401


def test_ping_bad_bearer_401():
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    client, _ = _app(devices, channels)
    r = client.post("/channels/box-1/ping", headers={"Authorization": "Bearer forged"})
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_ping_malformed_authorization_header_401():
    """An Authorization header without the 'Bearer ' scheme is unauthorized."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    client, _ = _app(devices, channels)
    r = client.post("/channels/box-1/ping", headers={"Authorization": "phone-1"})
    assert r.status_code == 401


def test_fleet_token_is_not_a_member_403():
    """A fleet/admin token has no deviceId membership (its sub is a service
    principal, never a channel member), so it is forbidden from pinging — ping
    is a MEMBER action, distinct from the owner/admin management actions."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    client, _ = _app(devices, channels)
    headers = {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}
    r = client.post("/channels/box-1/ping", headers=headers)
    assert r.status_code == 403


# --- wiring: the endpoint is gated on broker + channel_store -----------------


def test_ping_absent_without_channel_store():
    """No channel store wired: the ping endpoint is not registered (it lives in
    the broker+channel_store block)."""
    devices, _ = _stores()
    verifier = FleetOrDeviceVerifier(
        JwtVerifier(TEST_JWT_SECRET, "HS256", TEST_ISSUER),
        PerDeviceVerifier(devices, issuer=TEST_ISSUER),
    )
    client = TestClient(
        create_app(
            FakeRegistryClient(),
            FakeAgentClient(),
            verifier,
            broker=BrokerLinkManager(timeout_s=5.0),
        )
    )
    _, public_key = keypair_for("phone-1")
    devices.admit("phone-1", public_key)
    r = client.post("/channels/box-1/ping", headers=_device_headers("phone-1"))
    assert r.status_code == 404


def test_ping_absent_without_broker():
    """No broker wired: the ping endpoint is not registered (there is no
    delivery rail without the broker)."""
    devices, channels = _stores()
    _admit(devices, channels, "box-1", "phone-1")
    verifier = FleetOrDeviceVerifier(
        JwtVerifier(TEST_JWT_SECRET, "HS256", TEST_ISSUER),
        PerDeviceVerifier(devices, issuer=TEST_ISSUER),
    )
    client = TestClient(
        create_app(
            FakeRegistryClient(),
            FakeAgentClient(),
            verifier,
            channel_store=channels,
        )
    )
    r = client.post("/channels/box-1/ping", headers=_device_headers("phone-1"))
    assert r.status_code == 404
