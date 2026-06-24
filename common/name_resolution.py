"""Fail-fast validation of fabric endpoint names — application-config binding.

This is the **app-config** binding of the INFRA-1 name-resolution contract. Its
exceptions subclass :class:`common.config.ConfigError`, so the config layer
(``common/config.py``) catches them uniformly and fails fast on a bad endpoint,
while ``RawIPError`` and ``NameResolutionError`` stay distinguishable.

The framework-agnostic implementation lives in the ``bard_infra.nameres``
library package, which has **no dependency on ``common``** so it can be vendored
into other repos (and is where INFRA-2's ``RegistryResolver`` will land). The
pure, contract-defining pieces — the :class:`Resolver` ABC and the
:class:`EndpointResolution` value — are imported from there so both bindings
provably share one contract. The deliberate divergence is the exception bases
(``ConfigError`` here vs. framework-agnostic ``RuntimeError``/``ValueError`` in
the library) and the ``ConfigError``-raising ``_parse_port`` / empty-value check
below; those are intentional, not drift. (The earlier "vendored — keep in sync"
header was wrong: this file is a sibling binding, not a copy.)

Enforces the frozen contract: a fabric endpoint is a resolvable logical name,
optionally ``name:port``; a raw IP literal is a configuration error; an
unresolvable name crashes loudly.
"""

from __future__ import annotations

import ipaddress
import socket

from bard_infra.nameres import EndpointResolution, Resolver
from common.config import ConfigError

_MIN_PORT = 1
_MAX_PORT = 65535


class NameResolutionError(ConfigError):
    """A logical name could not be resolved to any address (fail-fast)."""


class RawIPError(ConfigError):
    """A raw IP literal was supplied where a logical name is required."""


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
