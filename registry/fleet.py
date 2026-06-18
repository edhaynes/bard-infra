"""Read-only fleet view for the management console (Sprint B5 / feature #64).

Joins the two record sets the Registry already keeps — per-device enrollment
records (``DeviceStore``, contracts/enrollment.schema.json) and agent
heartbeat records (``RegistryStore``) — into the ``FleetView`` shape frozen
in ``contracts/control-plane.openapi.yaml`` (``GET /fleet``). Pure functions,
no I/O: the route hands in the two lists and a timestamp, so the unit suite
drives every branch hermetically (CLAUDE.md §11).

Join key: ``deviceId == agentId`` — the B3 enroll path boots the agent under
the id it enrolled with, so one machine yields one row. An id present on only
one side still gets a row (enrolled-but-never-started, or a pre-identity
agent); the console never hides a machine.

``workgroup`` comes from the device record's console-assigned workgroup
(Sprint B6: ``DeviceStore.assign_workgroup`` persists it; see the additive
``DeviceRecord.workgroup`` in contracts/enrollment.schema.json). ``None``
when the device is not in a group or predates per-device identity.

This module is deliberately separate from ``registry/app.py`` (B3/B4 edit
that file in parallel); the app gains exactly one import and one new route.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from registry.store import STATUS_ACTIVE

CONNECTION_ONLINE = "online"
CONNECTION_STALE = "stale"
CONNECTION_OFFLINE = "offline"


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp for ``FleetView.generatedAt``."""
    return _dt.datetime.now(_dt.UTC).isoformat()


def _connection(agent: dict[str, Any] | None) -> str:
    if agent is None:
        return CONNECTION_OFFLINE
    if agent["status"] == STATUS_ACTIVE:
        return CONNECTION_ONLINE
    return CONNECTION_STALE


def _row(device_id: str, device: dict[str, Any] | None, agent: dict[str, Any] | None) -> dict:
    row: dict[str, Any] = {
        "id": device_id,
        "enrollment": device["state"] if device is not None else None,
        "connection": _connection(agent),
        # Liveness predates lastSeen; old persisted agents carry registeredAt only.
        "lastSeen": (agent.get("lastSeen") or agent.get("registeredAt")) if agent else None,
        # Console-assigned grouping (Sprint B6); None = not in a group.
        "workgroup": device.get("workgroup") if device is not None else None,
    }
    if device is not None and "label" in device:
        row["label"] = device["label"]
    if agent is not None:
        row["address"] = agent["address"]
        if "capabilities" in agent:
            row["capabilities"] = agent["capabilities"]
        if "powerProfile" in agent:
            row["powerProfile"] = agent["powerProfile"]
    return row


def build_fleet_view(
    agents: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """The ``GET /fleet`` response body (control-plane.openapi.yaml FleetView).

    ``agents`` is ``RegistryStore.list()`` output (status pre-annotated);
    ``devices`` is ``DeviceStore.list_devices()`` output (secrets stripped).
    """
    agents_by_id = {a["agentId"]: a for a in agents}
    devices_by_id = {d["deviceId"]: d for d in devices}
    rows = [
        _row(fleet_id, devices_by_id.get(fleet_id), agents_by_id.get(fleet_id))
        for fleet_id in devices_by_id.keys() | agents_by_id.keys()
    ]
    # Deterministic, human-friendly order: by display name, case-insensitive.
    rows.sort(key=lambda r: str(r.get("label") or r["id"]).lower())
    return {"devices": rows, "generatedAt": generated_at}
