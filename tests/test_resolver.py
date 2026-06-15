"""Hermetic tests for ``SystemResolver``.

No real DNS: ``socket.getaddrinfo`` is monkeypatched in every test. Covers the
success path (sorted, de-duplicated addresses), the ``gaierror`` failure path,
and the empty-result path.
"""

from __future__ import annotations

import socket

import pytest

from bard_infra.nameres.resolver import NameResolutionError, SystemResolver


def _addrinfo(addr: str, family: int = socket.AF_INET):
    """Build a getaddrinfo-shaped 5-tuple; only the sockaddr[0] is read."""
    sockaddr = (addr, 0) if family == socket.AF_INET else (addr, 0, 0, 0)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def test_resolve_returns_sorted_unique_addresses(monkeypatch) -> None:
    """A realistic infos list -> sorted, de-duplicated address strings."""
    infos = [
        _addrinfo("100.64.0.2"),
        _addrinfo("100.64.0.1"),
        _addrinfo("100.64.0.2"),  # duplicate, must collapse
    ]

    def fake_getaddrinfo(host, port):
        assert host == "gx10"
        assert port is None
        return infos

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert SystemResolver().resolve("gx10") == ["100.64.0.1", "100.64.0.2"]


def test_resolve_raises_on_gaierror(monkeypatch) -> None:
    """``socket.gaierror`` -> NameResolutionError, chained from the original."""

    def fake_getaddrinfo(host, port):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(NameResolutionError, match="name does not resolve") as exc:
        SystemResolver().resolve("nope")
    assert isinstance(exc.value.__cause__, socket.gaierror)


def test_resolve_raises_when_no_addresses(monkeypatch) -> None:
    """An empty infos list -> NameResolutionError (no addresses)."""

    def fake_getaddrinfo(host, port):
        return []

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(NameResolutionError, match="no addresses"):
        SystemResolver().resolve("silent")
