"""Fabric name resolution (INFRA-1) — framework-agnostic library.

Fabric endpoints are addressed by stable logical names, never raw IPs; the
backend that maps a name to a current address is swappable (MagicDNS for the
MVP, self-hosted DNS later — INFRA-2, where ``RegistryResolver`` will land
here). See ``docs/contracts/name-resolution.md``.

This package has **no dependency on ``common``**, so it is vendorable into other
repos. The :class:`Resolver` ABC and :class:`EndpointResolution` value defined
here are the single contract; ``common/name_resolution.py`` is the sibling
app-config binding that reuses them and rebases the exceptions on
``ConfigError`` for fail-fast config validation — an intentional split, not a
copy to keep in sync.
"""

from .resolver import NameResolutionError, Resolver, SystemResolver
from .validator import EndpointResolution, RawIPError, validate_endpoint

__all__ = [
    "NameResolutionError",
    "Resolver",
    "SystemResolver",
    "EndpointResolution",
    "RawIPError",
    "validate_endpoint",
]
