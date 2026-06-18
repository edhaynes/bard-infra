"""Fail-fast validation of fabric endpoint names (INFRA-1).

Enforces the frozen contract (``docs/contracts/name-resolution.md``): a fabric
endpoint is a resolvable logical name, optionally ``name:port``; a raw IP
literal is a configuration error; an unresolvable name crashes loudly.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .resolver import NameResolutionError, Resolver

_MIN_PORT = 1
_MAX_PORT = 65535


class RawIPError(ValueError):
    """A raw IP literal was supplied where a logical name is required."""


@dataclass(frozen=True)
class EndpointResolution:
    """The validated endpoint: its name, optional port, current addresses.

    Callers keep addressing the endpoint by ``name``; ``addresses`` is the
    current resolution, informational only (it may change as the node moves).
    """

    name: str
    port: int | None
    addresses: tuple[str, ...]


def _parse_port(text: str) -> int:
    port = int(text)
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise ValueError(f"port out of range ({_MIN_PORT}-{_MAX_PORT}): {port}")
    return port


def _split_host_port(value: str) -> tuple[str, int | None]:
    """Split ``name`` or ``name:port``; leave anything else as a bare host."""
    if value.count(":") == 1:
        head, _, tail = value.partition(":")
        if head and tail.isdigit():
            return head, _parse_port(tail)
    return value, None


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_endpoint(value: str, resolver: Resolver) -> EndpointResolution:
    """Validate a fabric endpoint config value and resolve it now.

    Rejects empty input (``ValueError``), a raw IP literal host
    (``RawIPError``), and an unresolvable name (``NameResolutionError``).
    Returns the parsed name, optional port, and current addresses.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("empty endpoint value; a logical name is required")
    host, port = _split_host_port(stripped)
    if _is_ip_literal(host):
        raise RawIPError(f"raw IP {host!r} is not allowed; address the fabric by logical name")
    addresses = resolver.resolve(host)
    if not addresses:
        raise NameResolutionError(f"name resolved to no addresses: {host!r}")
    return EndpointResolution(name=host, port=port, addresses=tuple(addresses))
