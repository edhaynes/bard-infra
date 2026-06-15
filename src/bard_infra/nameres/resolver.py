"""Resolver interface and the default OS-backed implementation.

The ``Resolver`` ABC is the swap seam (``coding-rules.md §3``): the MVP uses
``SystemResolver`` (the OS resolver, which Tailscale MagicDNS serves); a
registry-backed or self-hosted-DNS resolver (INFRA-2) substitutes behind the
same interface with no caller change.
"""

from __future__ import annotations

import socket
from abc import ABC, abstractmethod


class NameResolutionError(RuntimeError):
    """A logical name could not be resolved to any address (fail-fast, §0.11)."""


class Resolver(ABC):
    """Maps a logical fabric name to one or more current addresses."""

    @abstractmethod
    def resolve(self, host: str) -> list[str]:
        """Return current addresses for ``host``.

        Raises ``NameResolutionError`` if the name does not resolve.
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
