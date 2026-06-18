"""FastAPI app for the Agent Registry (registry.openapi.yaml).

Auth on registry endpoints is a bearer JWT in the Authorization header.
``create_app`` takes its collaborators by injection (CLAUDE.md §2).
"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Header, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.auth import AuthError, TokenVerifier
from common.cors import apply_cors
from common.errors import error_response
from common.metrics import AppMetrics, instrument
from common.placement import select_agent
from common.version import __version__
from registry.audit_log import (
    ACTION_APPROVE,
    ACTION_MEMBER_REMOVE,
    ACTION_PLUGIN_CONFIG,
    ACTION_PLUGIN_DISABLE,
    ACTION_PLUGIN_ENABLE,
    ACTION_RENAME,
    ACTION_REVOKE,
    ACTION_WORKGROUP,
    AuditLog,
)
from registry.channel_store import (
    ChannelExists,
    ChannelStore,
    InvalidInviteToken,
    InviteNotFound,
)
from registry.device_store import (
    DeviceNotFound,
    DeviceStore,
    InvalidJoinToken,
    InvalidPublicKey,
    InvalidStateTransition,
)
from registry.fleet import build_fleet_view, utcnow_iso
from registry.plugin_store import (
    InvalidPluginConfig,
    PluginNotFound,
    PluginNotMonitored,
    PluginStore,
)
from registry.store import AgentNotFound, RegistryStore


class RegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str = Field(min_length=1)
    address: str = Field(min_length=1)
    capabilities: list[str] | None = None
    powerProfile: dict | None = None


class EnrollBody(BaseModel):
    """POST /enroll body (contracts/enrollment.schema.json#/$defs/EnrollRequest)."""

    model_config = ConfigDict(extra="forbid")
    deviceId: str = Field(min_length=1)
    joinToken: str = Field(min_length=1)
    publicKey: str = Field(min_length=1)
    label: str | None = None


class SelfRegisterBody(BaseModel):
    """POST /devices/self-register body
    (contracts/enrollment.schema.json#/$defs/SelfRegisterRequest)."""

    model_config = ConfigDict(extra="forbid")
    deviceId: str = Field(min_length=1)
    publicKey: str = Field(min_length=1)
    label: str | None = None


class CreateChannelBody(BaseModel):
    """POST /channels body (contracts/invite.schema.json#/$defs/CreateChannelRequest)."""

    model_config = ConfigDict(extra="forbid")
    channelId: str = Field(min_length=1)
    label: str | None = None


class CreateInviteBody(BaseModel):
    """POST /invites body (contracts/invite.schema.json#/$defs/CreateInviteRequest)."""

    model_config = ConfigDict(extra="forbid")
    channelId: str = Field(min_length=1)
    label: str | None = None
    ttlSeconds: float | None = Field(default=None, gt=0)


class RedeemBody(BaseModel):
    """POST /invites/{token}/redeem body (contracts/invite.schema.json#/$defs/RedeemRequest)."""

    model_config = ConfigDict(extra="forbid")
    deviceId: str = Field(min_length=1)
    publicKey: str = Field(min_length=1)
    label: str | None = None


class RenameBody(BaseModel):
    """POST /devices/{id}/rename body (control-plane.openapi.yaml renameDevice)."""

    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1)


class WorkgroupBody(BaseModel):
    """POST /devices/{id}/workgroup body (control-plane.openapi.yaml
    assignWorkgroup). ``name`` null/omitted takes the device out of its group."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1)


class PluginScopeBody(BaseModel):
    """One enablement/config target (control-plane.openapi.yaml PluginScope):
    a device (target = deviceId) or a workgroup (target = the group NAME)."""

    model_config = ConfigDict(extra="forbid")
    scope: Literal["device", "workgroup"]
    target: str = Field(min_length=1)


class PluginEnableBody(PluginScopeBody):
    """POST /plugins/{id}/enable body (PluginEnableRequest)."""

    config: dict | None = None


class PluginConfigBody(PluginScopeBody):
    """PUT /plugins/{id}/config body (PluginConfigRequest)."""

    config: dict


class PluginHealthBody(BaseModel):
    """POST /plugins/{id}/health body (PluginHealthReport)."""

    model_config = ConfigDict(extra="forbid")
    deviceId: str = Field(min_length=1)
    status: Literal["ok", "failing"]
    detail: str | None = None


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def create_app(
    store: RegistryStore,
    verifier: TokenVerifier,
    *,
    cors_origins: list[str] | None = None,
    metrics: AppMetrics | None = None,
    device_store: DeviceStore | None = None,
    channel_store: ChannelStore | None = None,
    default_invite_ttl_s: float = 604800.0,
    audit_log: AuditLog | None = None,
    plugin_store: PluginStore | None = None,
) -> FastAPI:
    app = FastAPI(title="Bard Registry", version=__version__)
    apply_cors(app, cors_origins)
    instrument(app, metrics or AppMetrics("registry"))

    def _claims(authorization: str | None) -> dict | None:
        """Verified token claims, or None when the bearer is missing/bad.

        The management routes need the claims (the ``sub`` is the audit
        actor — Sprint B6); ``_authed`` keeps the boolean shape for the
        routes that only gate.
        """
        try:
            return verifier.verify(_bearer(authorization))
        except AuthError:
            return None

    def _authed(authorization: str | None) -> bool:
        return _claims(authorization) is not None

    def _caller_device_id(claims: dict) -> str | None:
        """The deviceId of a DEVICE-token caller, or None for a fleet/admin token.

        Discriminates the two credential types the FleetOrDeviceVerifier accepts
        (ADR-0016 / Step S5): a per-device token's ``sub`` resolves to an ACTIVE
        device in the store; a fleet/service token's ``sub`` (an agentId or
        service principal) never does. The verify already proved the token; this
        only asks WHICH kind authenticated, to decide ownership enforcement.
        Only ever called from the channel-store block (nested under
        ``device_store is not None``), so the store is always present here.
        """
        sub = claims.get("sub")
        if sub and device_store.device_public_key(sub) is not None:
            return sub
        return None

    def _owner_forbidden(claims: dict, channel_id: str) -> bool:
        """True when a DEVICE caller is not the channel's owner (-> 403). A fleet
        token (admin) bypasses ownership; a device caller MUST own the channel
        (ADR-0016 §4 — "the creator is the admin")."""
        device_id = _caller_device_id(claims)
        if device_id is None:
            return False  # fleet/admin token bypasses ownership
        return channel_store.channel_owner(channel_id) != device_id

    def _audit(
        claims: dict,
        action: str,
        device_id: str,
        detail: str | None = None,
        plugin_id: str | None = None,
        scope: str | None = None,
    ) -> None:
        """Record a management action when an audit log is wired (B6/B8)."""
        if audit_log is not None:
            audit_log.record(
                actor=claims["sub"],
                action=action,
                device_id=device_id,
                detail=detail,
                plugin_id=plugin_id,
                scope=scope,
            )

    @app.post("/register")
    def register(body: RegistrationBody, authorization: str | None = Header(default=None)):
        if not _authed(authorization):
            return error_response(401, "unauthorized")
        try:
            return store.register(body.agentId, body.address, body.capabilities, body.powerProfile)
        except ValidationError as exc:
            return error_response(400, "bad_request", detail=str(exc))

    @app.get("/agents")
    def list_agents(authorization: str | None = Header(default=None)):
        if not _authed(authorization):
            return error_response(401, "unauthorized")
        return store.list()

    @app.get("/pool")
    def pool(authorization: str | None = Header(default=None)):
        """Aggregated stranded-compute view across the registered fleet."""
        if not _authed(authorization):
            return error_response(401, "unauthorized")
        return store.pool()

    @app.get("/schedule")
    def schedule(gpu: bool = False, authorization: str | None = Header(default=None)):
        """Pick the best-fit node for a workload (GPU-preferred, CPU-fallback).

        Stale agents (no heartbeat within the TTL) are never placement
        candidates (feature #54)."""
        if not _authed(authorization):
            return error_response(401, "unauthorized")
        chosen = select_agent(store.list(include_stale=False), require_gpu=gpu)
        if chosen is None:
            return error_response(404, "not_found", detail="no agents available")
        return chosen

    @app.get("/agents/{agent_id}")
    def get_agent(agent_id: str, authorization: str | None = Header(default=None)):
        if not _authed(authorization):
            return error_response(401, "unauthorized")
        try:
            return store.get(agent_id)
        except AgentNotFound:
            return error_response(404, "not_found")

    # --- Per-device enrollment (Sprint B2 / ADR-0010) ------------------------
    # Registered only when device identity is enabled (a DeviceStore injected).
    # ``/enroll`` is gated by the join token in the body (the device's proof),
    # not the bearer; ``/devices*`` management endpoints are manager-only and
    # require the bearer (the existing verifier). See enrollment.schema.json.
    if device_store is not None:

        @app.post("/enroll")
        def enroll(body: EnrollBody):
            try:
                record = device_store.enroll(
                    body.deviceId, body.joinToken, body.publicKey, body.label
                )
            except InvalidJoinToken as exc:
                return error_response(401, "unauthorized", detail=str(exc))
            except InvalidPublicKey as exc:
                return error_response(400, "bad_request", detail=str(exc))
            except InvalidStateTransition as exc:
                return error_response(409, "conflict", detail=str(exc))
            return {"device": record}

        # --- Owner bootstrap (ADR-0016 / Step S5, closes #67) ----------------
        # OPEN endpoint: a device self-registers its public key and is admitted
        # ACTIVE with no invite and no manager approval — the bootstrap for the
        # device that creates and OWNS a box ("the creator is the admin"). This
        # retires the baked fleet token for owner actions. Idempotent for the
        # same deviceId+key; a deviceId re-used with a DIFFERENT key is a 409.
        # FIXME-ed 2026-06-18: rate-limit (bugs.md #59) — this is unauthenticated.
        @app.post("/devices/self-register")
        def self_register_device(body: SelfRegisterBody):
            try:
                record = device_store.self_register(body.deviceId, body.publicKey, body.label)
            except InvalidPublicKey as exc:
                return error_response(400, "bad_request", detail=str(exc))
            except InvalidStateTransition as exc:
                return error_response(409, "conflict", detail=str(exc))
            return {"device": record}

        @app.get("/devices")
        def list_devices(authorization: str | None = Header(default=None)):
            if not _authed(authorization):
                return error_response(401, "unauthorized")
            return device_store.list_devices()

        @app.post("/devices/{device_id}/approve")
        def approve_device(device_id: str, authorization: str | None = Header(default=None)):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                record = device_store.approve(device_id)
            except DeviceNotFound:
                return error_response(404, "not_found")
            except InvalidStateTransition as exc:
                return error_response(409, "conflict", detail=str(exc))
            _audit(claims, ACTION_APPROVE, device_id)
            return {"device": record}

        @app.post("/devices/{device_id}/revoke")
        def revoke_device(device_id: str, authorization: str | None = Header(default=None)):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                record = device_store.revoke(device_id)
            except DeviceNotFound:
                return error_response(404, "not_found")
            _audit(claims, ACTION_REVOKE, device_id)
            return {"device": record}

        # --- Console manage actions (Sprint B6 / feature #64 core) -----------
        # Contracted in control-plane.openapi.yaml; the device record's
        # ``workgroup`` is the additive B6 extension to enrollment.schema.json.
        @app.post("/devices/{device_id}/rename")
        def rename_device(
            device_id: str,
            body: RenameBody,
            authorization: str | None = Header(default=None),
        ):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                record = device_store.rename(device_id, body.label)
            except DeviceNotFound:
                return error_response(404, "not_found")
            _audit(claims, ACTION_RENAME, device_id, detail=body.label)
            return {"device": record}

        @app.post("/devices/{device_id}/workgroup")
        def assign_workgroup(
            device_id: str,
            body: WorkgroupBody,
            authorization: str | None = Header(default=None),
        ):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                record = device_store.assign_workgroup(device_id, body.name)
            except DeviceNotFound:
                return error_response(404, "not_found")
            _audit(claims, ACTION_WORKGROUP, device_id, detail=body.name)
            return {"device": record}

        # --- Channel invites (Sprint B3 / feature #67/#69) -------------------
        # The "send a link, click, you're in" flow. ``/invites`` is manager-only
        # (the owner creates the invite, behind the bearer). The redeem endpoint
        # is deliberately NOT bearer-gated: the invite token in the path IS the
        # authorization — the owner pre-authorized membership by sending the
        # link. Redemption admits the device ACTIVE in one step, no approve.
        if channel_store is not None:
            # --- Channel ownership (ADR-0016 / Step S5, "creator is admin") --
            # POST /channels creates a box. A DEVICE caller becomes the owner
            # (channel.owner = the token's sub); a fleet/admin token creates an
            # owner-null (admin) channel. Authed via the FleetOrDeviceVerifier
            # the app is built with, so a self-registered device's own token
            # creates its box — no baked fleet token (#67).
            @app.post("/channels")
            def create_channel(
                body: CreateChannelBody, authorization: str | None = Header(default=None)
            ):
                claims = _claims(authorization)
                if claims is None:
                    return error_response(401, "unauthorized")
                owner = _caller_device_id(claims)
                try:
                    channel = channel_store.create_channel(
                        body.channelId, owner=owner, label=body.label
                    )
                except ChannelExists as exc:
                    return error_response(409, "conflict", detail=str(exc))
                return {"channel": channel}

            @app.post("/invites")
            def create_invite(
                body: CreateInviteBody, authorization: str | None = Header(default=None)
            ):
                claims = _claims(authorization)
                if claims is None:
                    return error_response(401, "unauthorized")
                if _owner_forbidden(claims, body.channelId):
                    return error_response(403, "forbidden", detail="not the channel owner")
                ttl = body.ttlSeconds if body.ttlSeconds is not None else default_invite_ttl_s
                record, token, url = channel_store.create_invite(
                    body.channelId, ttl_s=ttl, label=body.label
                )
                return {"invite": record, "inviteToken": token, "inviteUrl": url}

            @app.post("/invites/{token}/redeem")
            def redeem_invite(token: str, body: RedeemBody):
                try:
                    device, channel_id = channel_store.redeem(
                        token, body.deviceId, body.publicKey, body.label
                    )
                except InvalidInviteToken as exc:
                    return error_response(401, "unauthorized", detail=str(exc))
                except InviteNotFound:
                    return error_response(404, "not_found")
                except InvalidPublicKey as exc:
                    return error_response(400, "bad_request", detail=str(exc))
                except InvalidStateTransition as exc:
                    return error_response(409, "conflict", detail=str(exc))
                return {"device": device, "channelId": channel_id}

            @app.get("/channels/{channel_id}/members")
            def channel_members(channel_id: str, authorization: str | None = Header(default=None)):
                claims = _claims(authorization)
                if claims is None:
                    return error_response(401, "unauthorized")
                if _owner_forbidden(claims, channel_id):
                    return error_response(403, "forbidden", detail="not the channel owner")
                return channel_store.members(channel_id)

            # E1 — remove a device from a channel's membership (manager-auth).
            # POST-action style, matching /devices/{id}/revoke (not DELETE):
            # the repo's mutating device-lifecycle verbs are all POST /{action}.
            # 404 on a non-member matches revoke_device's unknown-device 404 —
            # the manager learns the target was not actually a member. The drop
            # is audited like every other management mutation (B6).
            # NOTE: a recoverable "suspend" is a separate, open decision —
            # TODO(suspend): semantics pending Eddie. This is a hard remove.
            @app.post("/channels/{channel_id}/members/{device_id}/remove")
            def remove_channel_member(
                channel_id: str,
                device_id: str,
                authorization: str | None = Header(default=None),
            ):
                claims = _claims(authorization)
                if claims is None:
                    return error_response(401, "unauthorized")
                if _owner_forbidden(claims, channel_id):
                    return error_response(403, "forbidden", detail="not the channel owner")
                if not channel_store.remove_member(channel_id, device_id):
                    return error_response(404, "not_found")
                _audit(claims, ACTION_MEMBER_REMOVE, device_id, detail=channel_id)
                return channel_store.members(channel_id)

    # --- Read-only console fleet view (Sprint B5 / feature #64) --------------
    # Additive and isolated on purpose: B3/B4 modify the routes above in a
    # parallel branch; this block touches none of them. The join logic lives
    # in registry/fleet.py. Mutations from the console are Sprint B6.
    @app.get("/fleet")
    def fleet(authorization: str | None = Header(default=None)):
        if not _authed(authorization):
            return error_response(401, "unauthorized")
        devices = device_store.list_devices() if device_store is not None else []
        return build_fleet_view(store.list(), devices, utcnow_iso())

    # --- Management-action audit (Sprint B6 / feature #64) -------------------
    # Registered only when an AuditLog is wired, exactly as the enrollment
    # block keys off device_store. Read-only; entries come back newest first.
    if audit_log is not None:

        @app.get("/audit")
        def audit(authorization: str | None = Header(default=None)):
            if not _authed(authorization):
                return error_response(401, "unauthorized")
            return {"entries": audit_log.entries(), "generatedAt": utcnow_iso()}

    # --- Plugin manage (Sprint B8 / feature #65) ------------------------------
    # Registered only when a PluginStore is wired, exactly as the enrollment
    # block keys off device_store. The catalog is declared by the frozen
    # plugin-manifest contract; these routes manage the state AROUND it
    # (enable per device/workgroup, per-target config, reported health).
    # Every mutation is audited; health reports are telemetry, not audited.
    if plugin_store is not None:

        @app.get("/plugins")
        def plugins(authorization: str | None = Header(default=None)):
            if not _authed(authorization):
                return error_response(401, "unauthorized")
            return plugin_store.catalog_view()

        @app.post("/plugins/{plugin_id}/enable")
        def enable_plugin(
            plugin_id: str,
            body: PluginEnableBody,
            authorization: str | None = Header(default=None),
        ):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                status = plugin_store.enable(
                    plugin_id, scope=body.scope, target=body.target, config=body.config
                )
            except PluginNotFound:
                return error_response(404, "not_found")
            except InvalidPluginConfig as exc:
                return error_response(400, "bad_request", detail=str(exc))
            _audit(
                claims,
                ACTION_PLUGIN_ENABLE,
                body.target,
                detail=status["manifest"]["displayName"],
                plugin_id=plugin_id,
                scope=body.scope,
            )
            return status

        @app.post("/plugins/{plugin_id}/disable")
        def disable_plugin(
            plugin_id: str,
            body: PluginScopeBody,
            authorization: str | None = Header(default=None),
        ):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                status = plugin_store.disable(plugin_id, scope=body.scope, target=body.target)
            except PluginNotFound:
                return error_response(404, "not_found")
            _audit(
                claims,
                ACTION_PLUGIN_DISABLE,
                body.target,
                detail=status["manifest"]["displayName"],
                plugin_id=plugin_id,
                scope=body.scope,
            )
            return status

        @app.get("/plugins/{plugin_id}/config")
        def get_plugin_config(
            plugin_id: str,
            scope: Literal["device", "workgroup"] = Query(),
            target: str = Query(min_length=1),
            authorization: str | None = Header(default=None),
        ):
            if not _authed(authorization):
                return error_response(401, "unauthorized")
            try:
                return {"config": plugin_store.get_config(plugin_id, scope=scope, target=target)}
            except PluginNotFound:
                return error_response(404, "not_found")

        @app.put("/plugins/{plugin_id}/config")
        def set_plugin_config(
            plugin_id: str,
            body: PluginConfigBody,
            authorization: str | None = Header(default=None),
        ):
            claims = _claims(authorization)
            if claims is None:
                return error_response(401, "unauthorized")
            try:
                stored = plugin_store.set_config(
                    plugin_id, scope=body.scope, target=body.target, config=body.config
                )
            except PluginNotFound:
                return error_response(404, "not_found")
            except InvalidPluginConfig as exc:
                return error_response(400, "bad_request", detail=str(exc))
            _audit(
                claims,
                ACTION_PLUGIN_CONFIG,
                body.target,
                detail=plugin_store.manifest(plugin_id)["displayName"],
                plugin_id=plugin_id,
                scope=body.scope,
            )
            return {"config": stored}

        @app.post("/plugins/{plugin_id}/health")
        def report_plugin_health(
            plugin_id: str,
            body: PluginHealthBody,
            authorization: str | None = Header(default=None),
        ):
            if not _authed(authorization):
                return error_response(401, "unauthorized")
            try:
                return plugin_store.report_health(
                    plugin_id, device_id=body.deviceId, status=body.status, detail=body.detail
                )
            except PluginNotFound:
                return error_response(404, "not_found")
            except PluginNotMonitored as exc:
                return error_response(409, "conflict", detail=str(exc))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/version")
    def version():
        return {"version": __version__}

    return app
