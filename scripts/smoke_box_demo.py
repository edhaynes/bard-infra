"""Four-client box-join + ping demo (device-only model, ADR-0016).

A narrated, recordable end-to-end demo of the *built* fabric: four heterogeneous
clients — **Mac, iOS-sim, Linux-VM, Android-sim** — each generate their own
Ed25519 identity key, JOIN one shared "box" by redeeming an invite, open a live
receive-link, and PING each other across the box. This is the Path-A (device-only)
proof: no user tier, no management console, every device authenticated by its own
self-signed key.

Run:
    uv run python scripts/smoke_box_demo.py

It runs the real Registry + Router apps in-process (shared in-memory stores) and
drives the real endpoints — POST /channels, /invites, /invites/{token}/redeem,
GET /channels/{id}/members, the /v1/agent-link receive-link WebSocket, and
POST /channels/{id}/ping. Prints each step and a final SMOKE: PASS/FAIL.

Design notes (grounded in the code, not assumed):
- The box is created with a FLEET/admin token so it has no device-owner; all four
  devices join via *redeem* (one-step ACTIVE admission + membership). This avoids
  open bug #69 ("the box owner is not a member of their own box", fixed by the
  pending B2 sprint) so any member can ping the others on `main` as-is.
- A device proves identity with an EdDSA JWT (sub=deviceId) signed by the private
  key it generated on-device; the registry only ever stores the public key.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as _dt
import secrets
import sys
import tempfile
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
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

ISSUER = "bardllm-pro"
# Ephemeral per-run secrets — generated, never hardcoded (coding-rules §0.2),
# the same pattern scripts/smoke_local.py uses for its demo fleet secret.
FLEET_SECRET = secrets.token_urlsafe(32)
JOIN_SECRET = secrets.token_urlsafe(32)
INVITE_SECRET = secrets.token_urlsafe(32)
CHANNEL_ID = "box-demo"

# The four heterogeneous clients of this demo (deviceId, friendly name, emoji).
CLIENTS = [
    ("dev-mac", "Mac", "💻"),
    ("dev-ios-sim", "iOS-sim", "📱"),
    ("dev-linux-vm", "Linux-VM", "🐧"),
    ("dev-android-sim", "Android-sim", "🤖"),
]


def _device_keypair(label: str) -> tuple[Ed25519PrivateKey, str]:
    """A deterministic Ed25519 keypair for a demo device (ADR-0016 §3 device key);
    a real device generates this on-device and never shares the private half."""
    seed = (label.encode("utf-8") + b"\x00" * 32)[:32]
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return sk, base64.b64encode(pub).decode("ascii")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _mint_device_token(device_id: str, sk: Ed25519PrivateKey) -> str:
    """The device self-signs an EdDSA JWT with its own private key (ADR-0016 §2)."""
    now = _now()
    return jwt.encode(
        {"sub": device_id, "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        sk,
        algorithm="EdDSA",
    )


def _mint_fleet_token() -> str:
    """A fleet/admin HMAC token — used only to create the box + mint invites."""
    now = _now()
    return jwt.encode(
        {"sub": "bard-admin", "iss": ISSUER, "iat": now, "exp": now + _dt.timedelta(hours=1)},
        FLEET_SECRET,
        algorithm="HS256",
    )


class _NoRegistryClient:
    """The ping path never dials the registry; a stub satisfies create_app."""

    def lookup(self, agent_id: str, token: str) -> str:  # pragma: no cover - unused in demo
        raise RuntimeError("registry lookup not used in the box-ping demo")


class _NoAgentClient:
    def infer(self, address, request, token):  # pragma: no cover - unused in demo
        raise RuntimeError("agent infer not used in the box-ping demo")


def _banner(text: str) -> None:
    print(f"\n=== {text} ===")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bard-box-demo-"))

    # Shared stores: the SAME DeviceStore + ChannelStore instances are injected
    # into BOTH apps, so a device admitted by the Registry is instantly visible
    # to the Router's membership gate — no file reload needed in-process.
    device_store = DeviceStore(tmp / "devices.json", join_token_secret=JOIN_SECRET, issuer=ISSUER)
    channel_store = ChannelStore(
        device_store,
        tmp / "channels.json",
        invite_secret=INVITE_SECRET,
        issuer=ISSUER,
        invite_base_url="https://bard.example/join",
    )
    # One verifier shared by both apps: a fleet HMAC token OR a per-device EdDSA
    # token (resolved against the device's registered public key) both verify.
    verifier = FleetOrDeviceVerifier(
        JwtVerifier(FLEET_SECRET, "HS256", ISSUER),
        PerDeviceVerifier(device_store, issuer=ISSUER),
    )

    registry_app = create_registry(
        RegistryStore(tmp / "agents.json"),
        verifier,
        device_store=device_store,
        channel_store=channel_store,
    )
    router_app = create_router(
        _NoRegistryClient(),
        _NoAgentClient(),
        verifier,
        broker=BrokerLinkManager(),
        channel_store=channel_store,
    )
    registry = TestClient(registry_app)
    router = TestClient(router_app)

    fleet = _mint_fleet_token()
    fleet_auth = {"Authorization": f"Bearer {fleet}"}

    # Each device's on-device identity + self-signed token.
    keys = {did: _device_keypair(did) for did, _, _ in CLIENTS}
    tokens = {did: _mint_device_token(did, keys[did][0]) for did, _, _ in CLIENTS}
    names = {did: name for did, name, _ in CLIENTS}
    emoji = {did: e for did, _, e in CLIENTS}

    ok = True

    _banner("1. Admin creates the box")
    r = registry.post(
        "/channels", json={"channelId": CHANNEL_ID, "label": "Demo Box"}, headers=fleet_auth
    )
    print(f"POST /channels -> {r.status_code} {r.json()}")
    ok &= r.status_code == 200

    _banner("2. Each client generates a key and JOINS by redeeming an invite")
    for did, name, e in CLIENTS:
        inv = registry.post("/invites", json={"channelId": CHANNEL_ID}, headers=fleet_auth)
        token = inv.json()["inviteToken"]
        red = registry.post(
            f"/invites/{token}/redeem",
            json={"deviceId": did, "publicKey": keys[did][1], "label": name},
        )
        joined = red.status_code == 200
        ok &= joined
        print(
            f"  {e} {name:<12} keygen + redeem -> {red.status_code} "
            f"{'JOINED' if joined else 'FAILED ' + str(red.json())}"
        )

    _banner("3. Box membership (the four clients)")
    m = registry.get(f"/channels/{CHANNEL_ID}/members", headers=fleet_auth)
    member_ids = m.json().get("deviceIds", [])
    for did in member_ids:
        print(f"  • {emoji.get(did, '?')} {names.get(did, did)}  ({did})")
    ok &= set(member_ids) == {did for did, _, _ in CLIENTS}

    _banner("4. Each client opens a live receive-link, then pings fan out")
    with contextlib.ExitStack() as stack:
        sockets = {}
        for did, name, e in CLIENTS:
            ws = stack.enter_context(router.websocket_connect("/v1/agent-link"))
            ws.send_json({"type": "hello", "agentId": did, "authToken": tokens[did]})
            ack = ws.receive_json()
            up = ack.get("type") == "hello_ok"
            ok &= up
            print(f"  {e} {name:<12} receive-link -> {'UP' if up else 'FAILED'}")
            sockets[did] = ws

        # Two pings from two different clients on (notionally) different networks,
        # to show the cross-device, bidirectional fan-out.
        for sender in ("dev-mac", "dev-android-sim"):
            print(f"\n  {emoji[sender]} {names[sender]} pings the box:")
            resp = router.post(
                f"/channels/{CHANNEL_ID}/ping",
                headers={"Authorization": f"Bearer {tokens[sender]}"},
            )
            delivered = resp.json().get("delivered", [])
            ok &= resp.status_code == 200
            for did in member_ids:
                if did == sender:
                    continue
                frame = sockets[did].receive_json()
                got = frame.get("type") == "box.ping" and frame.get("from") == sender
                ok &= got
                print(
                    f"     -> {emoji[did]} {names[did]:<12} received '{frame.get('type')}' "
                    f"from {names.get(frame.get('from'), '?')}  {'✅' if got else '❌'}"
                )
            ok &= set(delivered) == {did for did, _, _ in CLIENTS if did != sender}

    print("\nSMOKE: PASS ✅" if ok else "\nSMOKE: FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
