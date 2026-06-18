"""Feature #55 — structured JSON logging (stdlib only).

Covers the JsonFormatter payload (ts/level/logger/msg, extras, exc_info),
the json|text|invalid format selection, and configure_logging wiring with
injected and default stream/logger.
"""

from __future__ import annotations

import io
import json
import logging
import sys

import pytest

from common.config import Config, ConfigError
from common.logging import JsonFormatter, configure_logging, make_formatter


def _capture_logger(name: str, formatter: logging.Formatter) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.handlers[:] = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


# --- JsonFormatter -------------------------------------------------------------


def test_json_formatter_emits_one_json_object_per_line():
    logger, stream = _capture_logger("t.basic", JsonFormatter())
    logger.info("hello %s", "world")
    payload = json.loads(stream.getvalue().strip())
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "t.basic"
    assert payload["ts"].endswith("+00:00")  # UTC ISO-8601


def test_json_formatter_includes_extras():
    logger, stream = _capture_logger("t.extras", JsonFormatter())
    logger.warning("with extras", extra={"request_id": "abc-123", "agent": "gpu-1"})
    payload = json.loads(stream.getvalue().strip())
    assert payload["request_id"] == "abc-123"
    assert payload["agent"] == "gpu-1"


def test_json_formatter_formats_exc_info():
    logger, stream = _capture_logger("t.exc", JsonFormatter())
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("inference failed")
    payload = json.loads(stream.getvalue().strip())
    assert payload["level"] == "ERROR"
    assert "ValueError: boom" in payload["exc_info"]


# --- make_formatter ------------------------------------------------------------


def test_make_formatter_selects_json_and_text():
    assert isinstance(make_formatter("json"), JsonFormatter)
    text = make_formatter("text")
    assert isinstance(text, logging.Formatter) and not isinstance(text, JsonFormatter)


def test_make_formatter_rejects_unknown_format():
    with pytest.raises(ConfigError, match="BARDPRO_LOG_FORMAT"):
        make_formatter("yaml")


# --- configure_logging ----------------------------------------------------------


def test_configure_logging_json_with_injected_logger_and_stream():
    stream = io.StringIO()
    logger = logging.getLogger("t.configured.json")
    logger.propagate = False
    configure_logging(Config(log_level="DEBUG"), stream=stream, logger=logger)
    logger.debug("structured")
    payload = json.loads(stream.getvalue().strip())
    assert payload["msg"] == "structured" and payload["level"] == "DEBUG"


def test_configure_logging_text_format():
    stream = io.StringIO()
    logger = logging.getLogger("t.configured.text")
    logger.propagate = False
    configure_logging(Config(log_format="text"), stream=stream, logger=logger)
    logger.info("plain line")
    line = stream.getvalue().strip()
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)
    assert "INFO" in line and "plain line" in line


def test_configure_logging_defaults_to_root_logger_and_stdout():
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        handler = configure_logging(Config())
        assert handler in root.handlers
        assert handler.stream is sys.stdout
        assert isinstance(handler.formatter, JsonFormatter)
        assert root.level == logging.INFO
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_config_log_format_default_is_json():
    assert Config().log_format == "json"
