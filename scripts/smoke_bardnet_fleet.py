"""Narrated real-roster onboard + ping fan-out over bardnet (PLAN_bardnet_fleet_test, T1.3).

The Tier-1 hermetic proof, recordable: the ACTUAL fleet roster
(``tests/fleet_roster.py``, the six devices from ``shared-rules/connectivity.md``)
is onboarded IN SUCCESSION onto one shared box, every reachable device opens a live
receive-link, one member pings, and the ping fans out across bardnet. The
deliberately-unreachable boxes (``beagle`` DOWN, ``barney`` unpowered) are reported
``offline`` — a clean result, not a failure (that offline-not-error branch is the
point of the ping contract).

Run:
    uv run python scripts/smoke_bardnet_fleet.py

It runs the real Registry + Router apps in-process (shared in-memory stores) and
drives the real endpoints, exactly as ``scripts/smoke_box_demo.py`` does — this one
just parametrizes the flow with the real fleet. Prints each step and a final
``SMOKE: PASS/FAIL``. Secrets are per-run ephemeral (never hardcoded, §0.2).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import secrets
import sys
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

# Make the package root importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.auth import JwtVerifier  # noqa: E402
from common.device_auth import FleetOrDeviceVerifier, PerDeviceVerifier  # noqa: E402
from registry.app import create_app as create_registry  # noqa: E402
from registry.channel_store import ChannelStore  # noqa: E402
from registry.device_store import DeviceStore  # noqa: E402
from registry.store import RegistryStore  # noqa: E402
from router.app import create_app as create_router  # noqa: E402
from router.broker import BrokerLinkManager  # noqa: E402
from tests.fakes.ed25519_helper import keypair_for, mint_device_token  # noqa: E402
from tests.fakes.jwt_helper import TEST_ISSUER  # noqa: E402
from tests.fleet_roster import FLEET_ROSTER  # noqa: E402

# Per-run ephemeral secrets — generated, never hardcoded (coding-rules §0.2).
FLEET_SECRET = secrets.token_urlsafe(32)
JOIN_SECRET = secrets.token_urlsafe(32)
INVITE_SECRET = secrets.token_urlsafe(32)
INVITE_BASE_URL = "https://join.bardllm.dev/i"
CHANNEL_ID = "box-fleet"


class _NoRegistryClient:
    """The ping path never dials the registry; a stub satisfies create_app."""

    def lookup(self, agent_id: str, token: str) -> str:  # pragma: no cover - unused in demo
        raise RuntimeError("registry lookup not used in the bardnet fleet demo")


class _NoAgentClient:
    def infer(self, address, request, token):  # pragma: no cover - unused in demo
        raise RuntimeError("agent infer not used in the bardnet fleet demo")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _fleet_token() -> str:
    now = _now()
    return jwt.encode(
        {"sub": "bard-admin", "iss": TEST_ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        FLEET_SECRET,
        algorithm="HS256",
    )


def _device_token(device_id: str) -> str:
    private_key, _ = keypair_for(device_id)
    return mint_device_token(device_id, private_key, issuer=TEST_ISSUER, ttl_s=3600)


def _banner(text: str) -> None:
    print(f"\n=== {text} ===")


def main() -> int:
    device_store = DeviceStore(None, join_token_secret=JOIN_SECRET, issuer=TEST_ISSUER)
    channel_store = ChannelStore(
        device_store,
        None,
        invite_secret=INVITE_SECRET,
        issuer=TEST_ISSUER,
        invite_base_url=INVITE_BASE_URL,
    )
    verifier = FleetOrDeviceVerifier(
        JwtVerifier(FLEET_SECRET, "HS256", TEST_ISSUER),
        PerDeviceVerifier(device_store, issuer=TEST_ISSUER),
    )
    registry = TestClient(
        create_registry(
            RegistryStore(None),
            verifier,
            device_store=device_store,
            channel_store=channel_store,
        )
    )
    router = TestClient(
        create_router(
            _NoRegistryClient(),
            _NoAgentClient(),
            verifier,
            broker=BrokerLinkManager(),
            channel_store=channel_store,
        )
    )

    fleet_auth = {"Authorization": f"Bearer {_fleet_token()}"}
    ok = True

    _banner("1. Admin creates the shared bardnet box")
    r = registry.post(
        "/channels", json={"channelId": CHANNEL_ID, "label": "Fleet Box"}, headers=fleet_auth
    )
    print(f"POST /channels -> {r.status_code}")
    ok &= r.status_code == 200

    _banner("2. Each fleet device generates a key and ONBOARDS in succession")
    for dev in FLEET_ROSTER:
        inv = registry.post("/invites", json={"channelId": CHANNEL_ID}, headers=fleet_auth)
        token = inv.json()["inviteToken"]
        _, public_key = keypair_for(dev.device_id)
        red = registry.post(
            f"/invites/{token}/redeem",
            json={"deviceId": dev.device_id, "publicKey": public_key, "label": dev.label},
        )
        joined = red.status_code == 200
        ok &= joined
        print(
            f"  {dev.label:<10} ({dev.platform:<32}) redeem -> {red.status_code} "
            f"{'ONBOARDED' if joined else 'FAILED'}"
        )

    _banner("3. Box membership (all six, in roster order)")
    member_ids = registry.get(f"/channels/{CHANNEL_ID}/members", headers=fleet_auth).json()[
        "deviceIds"
    ]
    for did in member_ids:
        print(f"  - {did}")
    ok &= member_ids == [dev.device_id for dev in FLEET_ROSTER]

    _banner("4. Reachable devices open a live link; one member pings the box")
    online = [dev for dev in FLEET_ROSTER if dev.reachable_default]
    offline = [dev for dev in FLEET_ROSTER if not dev.reachable_default]
    sender = online[0].device_id
    with contextlib.ExitStack() as stack:
        sockets = {}
        for dev in online:
            ws = stack.enter_context(router.websocket_connect("/v1/agent-link"))
            ws.send_json(
                {
                    "type": "hello",
                    "agentId": dev.device_id,
                    "authToken": _device_token(dev.device_id),
                }
            )
            up = ws.receive_json().get("type") == "hello_ok"
            ok &= up
            print(f"  {dev.label:<10} receive-link -> {'UP' if up else 'FAILED'}")
            sockets[dev.device_id] = ws
        for dev in offline:
            print(f"  {dev.label:<10} receive-link -> OFFLINE (expected: {dev.platform})")

        print(f"\n  {sender} pings the box:")
        resp = router.post(
            f"/channels/{CHANNEL_ID}/ping",
            headers={"Authorization": f"Bearer {_device_token(sender)}"},
        )
        ok &= resp.status_code == 200
        body = resp.json()
        for dev in online:
            if dev.device_id == sender:
                continue
            frame = sockets[dev.device_id].receive_json()
            got = frame.get("type") == "box.ping" and frame.get("from") == sender
            ok &= got
            print(
                f"     -> {dev.label:<10} received '{frame.get('type')}'  {'OK' if got else 'FAIL'}"
            )

        expected_delivered = {dev.device_id for dev in online if dev.device_id != sender}
        expected_offline = {dev.device_id for dev in offline}
        ok &= set(body.get("delivered", [])) == expected_delivered
        ok &= set(body.get("offline", [])) == expected_offline
        print(f"\n  delivered = {sorted(body.get('delivered', []))}")
        print(f"  offline   = {sorted(body.get('offline', []))}  (beagle/barney: down/unpowered)")

    print("\nSMOKE: PASS" if ok else "\nSMOKE: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
