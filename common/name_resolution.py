"""Fail-fast validation of fabric endpoint names.

# Vendored from bard-infra (src/bard_infra/nameres/). Canonical source is
# that repo; keep in sync. Ported 2026-06-15.

Enforces the frozen contract: a fabric endpoint is a resolvable logical name,
optionally ``name:port``; a raw IP literal is a configuration error; an
unresolvable name crashes loudly.

Errors are raised as :class:`ConfigError` subclasses (CLAUDE.md §1 fail-fast),
so callers that handle configuration failures uniformly catch them, while
``RawIPError`` and ``NameResolutionError`` stay distinguishable.

The :class:`Resolver` ABC is the swap seam (CLAUDE.md §2): the default
``SystemResolver`` (the OS resolver, which Tailscale MagicDNS serves) can be
substituted by a registry-backed or self-hosted-DNS resolver behind the same
interface with no caller change.
"""

from __future__ import annotations

import ipaddress
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass

from common.config import ConfigError

_MIN_PORT = 1
_MAX_PORT = 65535


class NameResolutionError(ConfigError):
    """A logical name could not be resolved to any address (fail-fast)."""


class RawIPError(ConfigError):
    """A raw IP literal was supplied where a logical name is required."""


class Resolver(ABC):
    """Maps a logical fabric name to one or more current addresses."""

    @abstractmethod
    def resolve(self, host: str) -> list[str]:
        """Return current addresses for ``host``.

        Raises :class:`NameResolutionError` if the name does not resolve.
        """
        raise NotImplementedError  # pragma: no cover - abstract


class SystemResolver(Resolver):
    """Resolve via the OS resolver (``socket.getaddrinfo``).

    On this fabric the OS resolver is served by Tailscale MagicDNS, so fleet
    names (``gx10``, ``frogstation``, ...) resolve with no extra infrastructure.
    """

    def resolve(self, host: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise NameResolutionError(f"name does not resolve: {host!r}") from exc
        addresses = sorted({info[4][0] for info in infos})
        if not addresses:
            raise NameResolutionError(f"name resolved to no addresses: {host!r}")
        return addresses


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
        raise ConfigError(f"port out of range ({_MIN_PORT}-{_MAX_PORT}): {port}")
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

    Rejects empty input (:class:`ConfigError`), a raw IP literal host
    (:class:`RawIPError`), and an unresolvable name
    (:class:`NameResolutionError`). Returns the parsed name, optional port, and
    current addresses.
    """
    stripped = value.strip()
    if not stripped:
        raise ConfigError("empty endpoint value; a logical name is required")
    host, port = _split_host_port(stripped)
    if _is_ip_literal(host):
        raise RawIPError(f"raw IP {host!r} is not allowed; address the fabric by logical name")
    addresses = resolver.resolve(host)
    if not addresses:
        raise NameResolutionError(f"name resolved to no addresses: {host!r}")
    return EndpointResolution(name=host, port=port, addresses=tuple(addresses))
