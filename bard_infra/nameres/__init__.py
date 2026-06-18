"""Fabric name resolution (INFRA-1).

Fabric endpoints are addressed by stable logical names, never raw IPs; the
backend that maps a name to a current address is swappable (MagicDNS for the
MVP, self-hosted DNS later — INFRA-2). See ``docs/contracts/name-resolution.md``.
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
