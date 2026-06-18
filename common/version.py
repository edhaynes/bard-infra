"""Canonical version accessor.

The single source of truth is the ``VERSION`` file at the project root
(``bardLLMPro/VERSION``); ``pyproject.toml`` reads it dynamically via hatchling.
At runtime we prefer installed package metadata (which carries that same value);
running from a source checkout falls back to reading ``VERSION`` directly, so
there is never a drifted literal (CLAUDE.md §11).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _resolve_version() -> str:
    # Prefer the canonical VERSION file when it sits beside the package (source
    # checkout and the container image, where the Containerfile copies it in).
    # This avoids stale metadata after an editable install + VERSION bump.
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    # Otherwise (installed wheel with no adjacent VERSION) use package metadata,
    # which hatchling baked from VERSION at build time.
    try:
        return _pkg_version("bardllm-pro")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _resolve_version()
