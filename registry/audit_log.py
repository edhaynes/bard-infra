"""Append-only audit log of management actions (Sprint B6 / feature #64).

Every console/management mutation — approve, revoke, rename, workgroup
assignment — is recorded as one entry: WHO (the manager token's ``sub``
claim), WHAT (the action), WHICH device, WHEN (the injected clock). The
shape is frozen in ``contracts/control-plane.openapi.yaml`` (``AuditEntry`` /
``AuditView``, served by ``GET /audit``).

Persistence follows the established per-concern-file rule (``DeviceStore``,
``ChannelStore``) but uses JSON Lines instead of a rewritten document:
an audit log must be *append-only*, and appending one line per entry means
past entries are never rewritten, truncated, or reordered on disk. The clock
is injected so the unit suite is hermetic (no real time, §11).
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ACTION_APPROVE = "approve"
ACTION_REVOKE = "revoke"
ACTION_RENAME = "rename"
ACTION_WORKGROUP = "workgroup"
# E1 — drop a device from a channel's membership (the membership counterpart to
# revoke; revoke clears enrollment but never touched channel membership).
ACTION_MEMBER_REMOVE = "member-remove"
# Sprint B8 (feature #65): plugin manage actions — additive AuditEntry
# extension in control-plane.openapi.yaml (optional pluginId/scope fields).
ACTION_PLUGIN_ENABLE = "plugin-enable"
ACTION_PLUGIN_DISABLE = "plugin-disable"
ACTION_PLUGIN_CONFIG = "plugin-config"


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class AuditLog:
    """JSONL-persisted, append-only management-action history.

    ``state_path=None`` keeps the log in memory only (unit tests, embeds).
    Entries are returned newest first by :meth:`entries` — the console shows
    the most recent action at the top.
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        clock: Callable[[], _dt.datetime] | None = None,
    ):
        self._path = Path(state_path) if state_path else None
        self._clock = clock or _utcnow
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._path and self._path.is_file():
            lines = self._path.read_text(encoding="utf-8").splitlines()
            self._entries = [json.loads(line) for line in lines if line.strip()]

    def record(
        self,
        *,
        actor: str,
        action: str,
        device_id: str,
        detail: str | None = None,
        plugin_id: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Append one entry (and one JSONL line). Never rewrites prior lines.

        For plugin actions (Sprint B8) ``device_id`` carries the acted-on
        TARGET — the deviceId, or the workgroup NAME for workgroup scope —
        and the optional ``plugin_id``/``scope`` fields identify the plugin
        (additive AuditEntry extension; B6 entries stay valid unchanged).
        """
        entry: dict[str, Any] = {
            "at": self._clock().isoformat(),
            "actor": actor,
            "action": action,
            "deviceId": device_id,
        }
        if detail is not None:
            entry["detail"] = detail
        if plugin_id is not None:
            entry["pluginId"] = plugin_id
        if scope is not None:
            entry["scope"] = scope
        self._entries.append(entry)
        if self._path:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        """All entries, newest first."""
        return list(reversed(self._entries))
