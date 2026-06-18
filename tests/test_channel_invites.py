"""Sprint B3 — channel invites, contract-first (contracts/invite.schema.json).

The "send a link, click, you're in" flow at the store level: an owner mints a
single-use channel invite; a worker redeems it and the device is admitted ACTIVE
into the channel in ONE step (no approve). Tests are written against the FROZEN
invite contract before/with the implementation (CLAUDE.md §11) and pin:

  - create -> redeem -> device active + channel member, in one call (no approve)
  - the invite is single-use (a second redeem fails)
  - an expired invite fails (injected clock, no sleeping)
  - a forged / wrong-secret / wrong-audience invite token fails
  - admission via the invite does NOT touch the fleet approve gate
  - a fleet (non-invite) enrollment still requires approve

No network, no real clock: the stores take an injectable clock + deterministic
id/secret generators so the suite is hermetic.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jsonschema
import jwt  # PyJWT
import pytest
from referencing import Registry, Resource

from registry.channel_store import (
    ChannelStore,
    InvalidInviteToken,
    InviteNotFound,
)
from registry.device_store import DeviceStore, InvalidStateTransition

ROOT = Path(__file__).resolve().parents[1]
INVITE_CONTRACT = ROOT / "contracts" / "invite.schema.json"
ENROLL_CONTRACT = ROOT / "contracts" / "enrollment.schema.json"

ISSUER = "bardllm-pro"
# Obvious >=32-byte placeholders — NOT credentials.
JOIN_SECRET = "join-token-secret-padding-0123456789-abc"  # noqa: S105
INVITE_SECRET = "channel-invite-secret-padding-0123456789"  # noqa: S105
ATTACKER_SECRET = "attacker-invite-secret-padding-0123456789"  # noqa: S105  # gitleaks:allow
BASE_URL = "https://join.bardllm.dev/i"
assert len(INVITE_SECRET.encode()) >= 32


class FakeClock:
    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 6, 12, 12, 0, 0, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


def _seq_secrets():
    n = 0

    def _gen() -> str:
        nonlocal n
        n += 1
        return f"device-secret-{n:02d}-padding-0123456789-abcdef"

    return _gen


def _seq_invite_ids():
    n = 0

    def _gen() -> str:
        nonlocal n
        n += 1
        return f"invite-{n:02d}"

    return _gen


def _devices(tmp_path: Path, clock: FakeClock) -> DeviceStore:
    return DeviceStore(
        tmp_path / "devices.json",
        join_token_secret=JOIN_SECRET,
        issuer=ISSUER,
        clock=clock,
        secret_factory=_seq_secrets(),
    )


def _channels(tmp_path: Path, clock: FakeClock, devices: DeviceStore) -> ChannelStore:
    return ChannelStore(
        devices,
        tmp_path / "channels.json",
        invite_secret=INVITE_SECRET,
        issuer=ISSUER,
        invite_base_url=BASE_URL,
        clock=clock,
        id_factory=_seq_invite_ids(),
    )


def _validator(contract: Path, defn: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(contract.read_text())
    enroll = json.loads(ENROLL_CONTRACT.read_text())
    registry = (
        Registry()
        .with_resource(uri=schema["$id"], resource=Resource.from_contents(schema))
        .with_resource(uri=enroll["$id"], resource=Resource.from_contents(enroll))
    )
    return jsonschema.Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/{defn}"}, registry=registry
    )


# --- contract conformance ----------------------------------------------------


def test_create_invite_matches_contract(tmp_path):
    clock = FakeClock()
    channels = _channels(tmp_path, clock, _devices(tmp_path, clock))
    record, token, url = channels.create_invite("north-site", ttl_s=3600, label="Crew")
    _validator(INVITE_CONTRACT, "InviteRecord").validate(record)
    _validator(INVITE_CONTRACT, "CreateInviteResponse").validate(
        {"invite": record, "inviteToken": token, "inviteUrl": url}
    )
    assert record["channelId"] == "north-site"
    assert record["redeemed"] is False
    assert record["label"] == "Crew"


def test_invite_url_embeds_the_token(tmp_path):
    clock = FakeClock()
    channels = _channels(tmp_path, clock, _devices(tmp_path, clock))
    _, token, url = channels.create_invite("north-site", ttl_s=3600)
    parts = urlsplit(url)
    assert url.startswith(BASE_URL)
    assert parse_qs(parts.query)["invite"] == [token]


def test_redeem_response_matches_contract(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    device, secret, channel_id = channels.redeem(token, "phone-1", "Bob's phone")
    _validator(INVITE_CONTRACT, "RedeemResponse").validate(
        {"device": device, "deviceSecret": secret, "channelId": channel_id}
    )
    _validator(ENROLL_CONTRACT, "DeviceRecord").validate(device)


# --- the headline: one-click redemption, no approve --------------------------


def test_create_redeem_admits_active_member_in_one_step(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)

    device, secret, channel_id = channels.redeem(token, "phone-1", "Bob's phone")

    # Active immediately — no pending, no approve call anywhere.
    assert device["state"] == "active"
    assert device["deviceId"] == "phone-1"
    assert channel_id == "north-site"
    assert len(secret.encode()) >= 32
    # The device is a channel member.
    assert channels.is_member("north-site", "phone-1")
    assert channels.members("north-site")["deviceIds"] == ["phone-1"]
    # And the device store agrees it is active (the secret resolves).
    assert devices.device_secret("phone-1") == secret
    assert "deviceSecret" not in device


def test_redeemed_device_token_verifies(tmp_path):
    """A device admitted by invite can mint + verify a per-device token — the
    redemption produced a real, usable credential."""
    from common.device_auth import PerDeviceVerifier

    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    _, secret, _ = channels.redeem(token, "phone-1")

    verifier = PerDeviceVerifier(devices, issuer=ISSUER, clock=clock)
    device_token = devices.mint_device_token("phone-1", secret, ttl_s=3600)
    assert verifier.verify(device_token)["sub"] == "phone-1"


# --- single-use --------------------------------------------------------------


def test_invite_is_single_use(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(token, "phone-1")
    with pytest.raises(InvalidInviteToken, match="already been redeemed"):
        channels.redeem(token, "phone-2")
    # The second device was never admitted.
    assert not channels.is_member("north-site", "phone-2")


def test_redeem_records_consumption_on_invite(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    record, token, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(token, "phone-1")
    refreshed = channels._invites[record["inviteId"]]
    assert refreshed["redeemed"] is True
    assert refreshed["redeemedBy"] == "phone-1"
    assert refreshed["redeemedAt"] is not None


# --- expiry ------------------------------------------------------------------


def test_expired_invite_rejected(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=60)
    clock.advance(120)
    with pytest.raises(InvalidInviteToken, match="expired"):
        channels.redeem(token, "phone-1")
    assert not channels.is_member("north-site", "phone-1")


# --- forged / wrong tokens ---------------------------------------------------


def test_redeem_rejects_forged_invite_token(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    now = clock()
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "bard-channel-invite",
            "cid": "north-site",
            "jti": "invite-forged",
            "iat": now,
            "exp": now + _dt.timedelta(hours=1),
        },
        ATTACKER_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidInviteToken):
        channels.redeem(forged, "phone-1")


def test_redeem_rejects_garbage_token(tmp_path):
    clock = FakeClock()
    channels = _channels(tmp_path, clock, _devices(tmp_path, clock))
    with pytest.raises(InvalidInviteToken):
        channels.redeem("not.a.jwt", "phone-1")


def test_redeem_rejects_wrong_audience_token(tmp_path):
    """A fleet join token (different audience) cannot be redeemed as an invite."""
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    # Sign with the invite secret but the WRONG audience + missing cid/jti.
    now = clock()
    wrong = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "bard-device-enroll",
            "iat": now,
            "exp": now + _dt.timedelta(hours=1),
        },
        INVITE_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidInviteToken):
        channels.redeem(wrong, "phone-1")


def test_redeem_unknown_jti_is_not_found(tmp_path):
    """A token correctly signed by us but carrying a jti we never issued (e.g.
    a pruned/replayed invite) is treated as not-found, not a signature error."""
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    now = clock()
    orphan = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "bard-channel-invite",
            "cid": "north-site",
            "jti": "never-issued",
            "iat": now,
            "exp": now + _dt.timedelta(hours=1),
        },
        INVITE_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InviteNotFound):
        channels.redeem(orphan, "phone-1")


# --- redeem onto an existing deviceId fails, invite NOT consumed -------------


def test_redeem_existing_device_id_conflicts_and_preserves_invite(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    # A device already exists (admitted by an earlier invite).
    _, t1, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(t1, "phone-1")
    # A fresh invite redeemed onto the SAME deviceId must conflict.
    rec, t2, _ = channels.create_invite("south-site", ttl_s=3600)
    with pytest.raises(InvalidStateTransition):
        channels.redeem(t2, "phone-1")
    # The second invite is preserved (not burned) so a retry with a fresh id works.
    assert channels._invites[rec["inviteId"]]["redeemed"] is False
    channels.redeem(t2, "phone-2")
    assert channels.is_member("south-site", "phone-2")


# --- fleet path still requires approve (the contrast) ------------------------


def test_fleet_enrollment_still_requires_approve(tmp_path):
    """The invite path skips approve, but the fleet path does NOT: an enrolled
    device is pending until a manager approves it."""
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    jt = devices.issue_join_token(ttl_s=600)
    record = devices.enroll("node-gpu", jt)
    assert record["state"] == "pending"
    # No secret until approve.
    assert devices.device_secret("node-gpu") is None
    devices.approve("node-gpu")
    assert devices.get_device("node-gpu")["state"] == "active"


# --- membership reads + persistence ------------------------------------------


def test_members_unknown_channel_is_empty(tmp_path):
    clock = FakeClock()
    channels = _channels(tmp_path, clock, _devices(tmp_path, clock))
    assert channels.members("ghost") == {"channelId": "ghost", "deviceIds": []}


def test_two_devices_join_same_channel(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    for dev in ("phone-1", "phone-2"):
        _, token, _ = channels.create_invite("north-site", ttl_s=3600)
        channels.redeem(token, dev)
    assert channels.members("north-site")["deviceIds"] == ["phone-1", "phone-2"]


# --- member removal (E1) -----------------------------------------------------


def test_remove_member_drops_an_existing_member(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    for dev in ("phone-1", "phone-2"):
        _, token, _ = channels.create_invite("north-site", ttl_s=3600)
        channels.redeem(token, dev)

    assert channels.remove_member("north-site", "phone-1") is True
    assert not channels.is_member("north-site", "phone-1")
    # The other member is untouched.
    assert channels.members("north-site")["deviceIds"] == ["phone-2"]


def test_remove_member_non_member_is_false_noop(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(token, "phone-1")
    # Not a member of this channel.
    assert channels.remove_member("north-site", "ghost") is False
    # Membership unchanged.
    assert channels.members("north-site")["deviceIds"] == ["phone-1"]


def test_remove_member_unknown_channel_is_false(tmp_path):
    clock = FakeClock()
    channels = _channels(tmp_path, clock, _devices(tmp_path, clock))
    assert channels.remove_member("ghost-channel", "phone-1") is False


def test_remove_last_member_clears_channel_entry(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(token, "phone-1")
    assert channels.remove_member("north-site", "phone-1") is True
    # The emptied channel projects to [] (same as an unknown channel).
    assert channels.members("north-site")["deviceIds"] == []
    assert "north-site" not in channels._memberships


def test_remove_member_persists_across_reload(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    for dev in ("phone-1", "phone-2"):
        _, token, _ = channels.create_invite("north-site", ttl_s=3600)
        channels.redeem(token, dev)
    channels.remove_member("north-site", "phone-1")

    reloaded = ChannelStore(
        devices,
        tmp_path / "channels.json",
        invite_secret=INVITE_SECRET,
        issuer=ISSUER,
        invite_base_url=BASE_URL,
        clock=clock,
        id_factory=_seq_invite_ids(),
    )
    assert reloaded.members("north-site")["deviceIds"] == ["phone-2"]


def test_channel_store_persists_and_reloads(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = _channels(tmp_path, clock, devices)
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(token, "phone-1")

    # A fresh ChannelStore over the same file sees the membership + consumed invite.
    reloaded = ChannelStore(
        devices,
        tmp_path / "channels.json",
        invite_secret=INVITE_SECRET,
        issuer=ISSUER,
        invite_base_url=BASE_URL,
        clock=clock,
        id_factory=_seq_invite_ids(),
    )
    assert reloaded.is_member("north-site", "phone-1")


def test_channel_store_without_path_does_not_persist(tmp_path):
    clock = FakeClock()
    devices = _devices(tmp_path, clock)
    channels = ChannelStore(
        devices,
        None,
        invite_secret=INVITE_SECRET,
        issuer=ISSUER,
        invite_base_url=BASE_URL,
        clock=clock,
        id_factory=_seq_invite_ids(),
    )
    _, token, _ = channels.create_invite("north-site", ttl_s=3600)
    channels.redeem(token, "phone-1")
    assert channels.is_member("north-site", "phone-1")


# --- constructor guards ------------------------------------------------------


def test_channel_store_requires_invite_secret(tmp_path):
    with pytest.raises(ValueError, match="invite_secret is required"):
        ChannelStore(
            _devices(tmp_path, FakeClock()),
            None,
            invite_secret="",
            issuer=ISSUER,
            invite_base_url=BASE_URL,
        )


def test_channel_store_requires_base_url(tmp_path):
    with pytest.raises(ValueError, match="invite_base_url is required"):
        ChannelStore(
            _devices(tmp_path, FakeClock()),
            None,
            invite_secret=INVITE_SECRET,
            issuer=ISSUER,
            invite_base_url="",
        )


def test_invite_base_url_trailing_slash_stripped(tmp_path):
    clock = FakeClock()
    channels = ChannelStore(
        _devices(tmp_path, clock),
        None,
        invite_secret=INVITE_SECRET,
        issuer=ISSUER,
        invite_base_url="https://join.bardllm.dev/i/",
        clock=clock,
        id_factory=_seq_invite_ids(),
    )
    _, _, url = channels.create_invite("north-site", ttl_s=3600)
    assert url.startswith("https://join.bardllm.dev/i?")
