"""Structured logging for the fleet apps (feature #55). Stdlib only.

``JsonFormatter`` emits one JSON object per line — ``ts`` (UTC ISO-8601),
``level``, ``logger``, ``msg``, plus any ``extra={...}`` fields and a
formatted ``exc_info`` when present. ``configure_logging`` wires it (or a
plain-text formatter) onto a logger from config: ``BARDPRO_LOG_FORMAT`` is
``json`` (default) or ``text``; level comes from ``BARDPRO_LOG_LEVEL``.
Logs go to stdout (container-friendly, CLAUDE.md §5); stream and target
logger are injectable for tests.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sys
from typing import TextIO

from common.config import Config, ConfigError

#: Attributes present on every LogRecord — anything beyond these (and the
#: two computed by Formatter) was passed via ``extra=`` and gets emitted.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg (+ extras, exc_info)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": _dt.datetime.fromtimestamp(record.created, _dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def make_formatter(log_format: str) -> logging.Formatter:
    """Build the configured formatter; unknown formats fail fast (§1)."""
    if log_format == "json":
        return JsonFormatter()
    if log_format == "text":
        return logging.Formatter(TEXT_FORMAT)
    raise ConfigError(f"Invalid BARDPRO_LOG_FORMAT={log_format!r} (expected 'json' or 'text')")


def configure_logging(
    config: Config,
    *,
    stream: TextIO | None = None,
    logger: logging.Logger | None = None,
) -> logging.Handler:
    """Install the configured formatter + level on ``logger`` (default: root)."""
    target = logger if logger is not None else logging.getLogger()
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(make_formatter(config.log_format))
    target.handlers[:] = [handler]
    target.setLevel(config.log_level.upper())
    return handler
