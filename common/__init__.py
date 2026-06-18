"""Shared, import-only library for Bard lanes (Phase 0 contract layer).

Lanes import from here; they do not edit it. ``protocol`` models are imported
explicitly by consumers to avoid pulling pydantic into config-only callers.
"""

from common.config import Config, ConfigError, load_config
from common.version import __version__

__all__ = ["Config", "ConfigError", "load_config", "__version__"]
