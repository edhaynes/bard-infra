"""Channel invites + membership store (Sprint B3 / feature #67/#69).

The "send a link, click, you're in" flow, contract-frozen in
``contracts/invite.schema.json``. An owner/manager mints an INVITE for a
channel; a worker opens the link and redeems it; the device is admitted ACTIVE
into that channel in ONE step (no manager approve), because the owner
pre-authorized membership by sending the link. This is deliberately distinct
from the fleet enrollment lifecycle (``registry/device_store.py``): fleet
enrollment still requires approve; an invite does not.

Persistence lives in its OWN JSON file, parallel to (never merged into) the
``DeviceStore`` device file and the agent ``RegistryStore`` file — the same
"separate file per concern" rule B2 already follows so each store's persisted
shape stays a stable contract. The clock and id/secret generators are injected
so the suite is hermetic (no real time, no real randomness; §11 no-network).

Invite tokens are signed JWTs (audience ``bard-channel-invite``, distinct from
the fleet join token's ``bard-device-enroll``), carrying the channelId (``cid``)
and a unique id (``jti``). The store burns the ``jti`` on first successful
redeem, so an invite is single-use; expiry is checked against the injected
clock. Device admission is delegated to the injected ``DeviceStore`` so the
per-device key machinery (Ed25519 public-key registration; ADR-0016/S3) is not
re-implemented here — redemption registers the device's public key and returns
no secret (the device self-signs with the private key it never discloses).
"""

from __future__ import annotations

import datetime as _dt
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jwt  # PyJWT

from registry.device_store import DeviceStore

_ALGO = "HS256"
#: Marks an invite token apart from a fleet join token and a device token: a
#: channel invite MUST NOT be usable as either (different audience).
_INVITE_AUDIENCE = "bard-channel-invite"
#: Query parameter the invite URL carries the token in.
_INVITE_QUERY_PARAM = "invite"


class InviteNotFound(KeyError):
    """Raised when an unknown / unparseable invite token is redeemed (404)."""


class InvalidInviteToken(ValueError):
    """Raised when an invite token is malformed, expired, untrusted, or already
    consumed (single-use). Maps to 401 at the HTTP layer."""


class ChannelExists(ValueError):
    """Raised when creating a channel whose channelId already exists (maps to
    409). A channel's owner is fixed at creation (ADR-0016 / Step S5 — "the
    creator is the admin"), so a re-create MUST NOT silently re-own it."""


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _default_invite_id() -> str:
    return secrets.token_urlsafe(16)


class ChannelStore:
    """JSON-persisted channel invites + per-channel device membership.

    Persisted shape (its own file)::

        {
          "invites":     {inviteId: {..InviteRecord..}},
          "memberships": {channelId: [deviceId, ...]},
          "channels":    {channelId: {channelId, owner, label?}}
        }

    The ``channels`` map (ADR-0016 / Step S5) records a channel's OWNER — the
    deviceId of the device that created it ("the creator is the admin"), or
    ``None`` for an admin/fleet-created channel. Ownership gates who may invite
    into and manage the channel; a device owner is enforced at the HTTP layer.
    """

    def __init__(
        self,
        device_store: DeviceStore,
        state_path: str | Path | None = None,
        *,
        invite_secret: str,
        issuer: str,
        invite_base_url: str,
        clock: Callable[[], _dt.datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ):
        if not invite_secret:
            raise ValueError("invite_secret is required")
        if not invite_base_url:
            raise ValueError("invite_base_url is required")
        self._devices = device_store
        self._path = Path(state_path) if state_path else None
        self._invite_secret = invite_secret
        self._issuer = issuer
        self._base_url = invite_base_url.rstrip("/")
        self._clock = clock or _utcnow
        self._id_factory = id_factory or _default_invite_id
        self._invites: dict[str, dict[str, Any]] = {}
        self._memberships: dict[str, list[str]] = {}
        self._channels: dict[str, dict[str, Any]] = {}
        self._load()

    # --- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self._path and self._path.is_file():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._invites = data.get("invites", {})
            self._memberships = data.get("memberships", {})
            self._channels = data.get("channels", {})

    def save(self) -> None:
        if self._path:
            payload = {
                "invites": self._invites,
                "memberships": self._memberships,
                "channels": self._channels,
            }
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # --- channel ownership (ADR-0016 / Step S5) ------------------------------

    def create_channel(
        self, channel_id: str, *, owner: str | None, label: str | None = None
    ) -> dict[str, Any]:
        """Create a channel owned by ``owner`` (a deviceId, or ``None`` for an
        admin/fleet-created channel). The owner is fixed at creation — "the
        creator is the admin" (ADR-0016 §4). Rejects a channelId that already
        exists so a re-create can never silently re-own a channel.
        """
        if channel_id in self._channels:
            raise ChannelExists(f"channel {channel_id!r} already exists")
        record: dict[str, Any] = {"channelId": channel_id, "owner": owner, "label": label}
        self._channels[channel_id] = record
        self.save()
        return dict(record)

    def channel_owner(self, channel_id: str) -> str | None:
        """The owning deviceId for a channel, or ``None`` when the channel is
        unknown OR was admin/fleet-created (no device owner). Callers needing to
        distinguish 'unknown' from 'unowned' use :meth:`channel_exists`."""
        record = self._channels.get(channel_id)
        return record.get("owner") if record is not None else None

    def channel_exists(self, channel_id: str) -> bool:
        return channel_id in self._channels

    # --- invite creation -----------------------------------------------------

    def create_invite(
        self, channel_id: str, *, ttl_s: float, label: str | None = None
    ) -> tuple[dict[str, Any], str, str]:
        """Mint a single-use channel invite. Returns (record, token, url)."""
        now = self._clock()
        expires = now + _dt.timedelta(seconds=ttl_s)
        invite_id = self._id_factory()
        token = jwt.encode(
            {
                "iss": self._issuer,
                "aud": _INVITE_AUDIENCE,
                "cid": channel_id,
                "jti": invite_id,
                "iat": now,
                "exp": expires,
            },
            self._invite_secret,
            algorithm=_ALGO,
        )
        record: dict[str, Any] = {
            "inviteId": invite_id,
            "channelId": channel_id,
            "createdAt": now.isoformat(),
            "expiresAt": expires.isoformat(),
            "redeemed": False,
            "redeemedAt": None,
            "redeemedBy": None,
        }
        if label is not None:
            record["label"] = label
        self._invites[invite_id] = record
        self.save()
        url = f"{self._base_url}?{_INVITE_QUERY_PARAM}={quote(token, safe='')}"
        return dict(record), token, url

    # --- redemption ----------------------------------------------------------

    def redeem(
        self, token: str, device_id: str, public_key: str, label: str | None = None
    ) -> tuple[dict[str, Any], str]:
        """Verify an invite token and admit the device ACTIVE into the channel
        in one step (no approve), registering the public key the device
        generated on-device. Returns (device_record, channelId). Single-use: the
        invite is burned on success. No secret is returned — the device self-signs
        with the private key it never disclosed (ADR-0016 §3).

        Order matters (fail fast): validate the token first, then the
        single-use/known state, THEN admit the device (which validates the public
        key). If admission fails (bad public key, or deviceId already exists), the
        invite is NOT consumed, so a legitimate retry still works.
        """
        channel_id, invite_id = self._verify_invite_token(token)
        record = self._invites.get(invite_id)
        if record is None:
            # Signed by us with a jti we never issued (or one already pruned):
            # treat as unknown rather than a forged-signature case.
            raise InviteNotFound(invite_id)
        if record["redeemed"]:
            raise InvalidInviteToken("invite has already been redeemed")

        device_record = self._devices.admit(device_id, public_key, label)

        # ``admit`` rejects a deviceId that already exists, so a successfully
        # admitted device is brand new and cannot already be a channel member —
        # the append needs no dedup guard.
        self._memberships.setdefault(channel_id, []).append(device_id)
        record["redeemed"] = True
        record["redeemedAt"] = self._clock().isoformat()
        record["redeemedBy"] = device_id
        self.save()
        return device_record, channel_id

    def _verify_invite_token(self, token: str) -> tuple[str, str]:
        """Return (channelId, inviteId) for a well-formed, unexpired, trusted
        invite token. Expiry is checked against the INJECTED clock (verify_exp
        disabled) so tests advance a fake clock instead of sleeping."""
        try:
            claims = jwt.decode(
                token,
                self._invite_secret,
                algorithms=[_ALGO],
                audience=_INVITE_AUDIENCE,
                issuer=self._issuer,
                options={
                    "require": ["exp", "iss", "aud", "cid", "jti"],
                    "verify_exp": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidInviteToken(str(exc)) from exc
        if claims["exp"] < self._clock().timestamp():
            raise InvalidInviteToken("invite token has expired")
        return claims["cid"], claims["jti"]

    # --- reads ---------------------------------------------------------------

    def members(self, channel_id: str) -> dict[str, Any]:
        """ChannelMembership projection (empty list for an unknown channel)."""
        return {
            "channelId": channel_id,
            "deviceIds": list(self._memberships.get(channel_id, [])),
        }

    def is_member(self, channel_id: str, device_id: str) -> bool:
        return device_id in self._memberships.get(channel_id, [])

    # --- membership mutation -------------------------------------------------

    def remove_member(self, channel_id: str, device_id: str) -> bool:
        """Drop ``device_id`` from ``channel_id``'s membership.

        Returns True if the device WAS a member and was removed; False if it was
        not a member (unknown channel or unknown device) — so the caller can
        choose the REST convention (idempotent 200 vs 404). Removal is
        idempotent at the store level: removing a non-member is a safe no-op.

        This is the membership counterpart to the device lifecycle's revoke
        (E1 gap): revoke clears a device's enrollment/secret in the DeviceStore
        but never touched channel membership, so a revoked device lingered in
        ``members()``. ``remove_member`` is the explicit drop. Persisted on
        success only (a no-op leaves the file untouched).

        # TODO(suspend): a recoverable "suspend" (disable membership but keep
        # the row for later restore) is a distinct, open-decision semantic —
        # pending Eddie. This is a hard remove only.
        """
        members = self._memberships.get(channel_id)
        if not members or device_id not in members:
            return False
        members.remove(device_id)
        if not members:
            # Don't leave an empty membership list behind; an unknown channel and
            # an emptied channel both project to [] via ``members()``.
            del self._memberships[channel_id]
        self.save()
        return True
