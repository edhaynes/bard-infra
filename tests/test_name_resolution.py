"""Unit tests for the vendored name-resolution validator (common/name_resolution.py).

Hermetic: no real network. ``SystemResolver`` is tested by monkeypatching
``socket.getaddrinfo``; ``validate_endpoint`` is tested with injected
``Resolver`` doubles (CLAUDE.md §2 dependency injection). Targets 100% line and
branch coverage of the module.
"""

from __future__ import annotations

import socket

import pytest

from common.config import ConfigError
from common.name_resolution import (
    EndpointResolution,
    NameResolutionError,
    RawIPError,
    Resolver,
    SystemResolver,
    _is_ip_literal,
    _parse_port,
    _split_host_port,
    validate_endpoint,
)


class FakeResolver(Resolver):
    """Test double: returns a fixed address list (or raises) per construction."""

    def __init__(self, addresses=None, *, raises=None):
        self._addresses = addresses
        self._raises = raises
        self.calls: list[str] = []

    def resolve(self, host: str) -> list[str]:
        self.calls.append(host)
        if self._raises is not None:
            raise self._raises
        return list(self._addresses)


# --- type hierarchy --------------------------------------------------------


def test_error_classes_are_configerror_subclasses():
    assert issubclass(RawIPError, ConfigError)
    assert issubclass(NameResolutionError, ConfigError)


# --- _parse_port -----------------------------------------------------------


def test_parse_port_valid():
    assert _parse_port("8080") == 8080
    assert _parse_port("1") == 1
    assert _parse_port("65535") == 65535


def test_parse_port_out_of_range():
    with pytest.raises(ConfigError):
        _parse_port("99999")


# --- _split_host_port ------------------------------------------------------


def test_split_host_port_name_with_port():
    assert _split_host_port("router:8080") == ("router", 8080)


def test_split_host_port_non_digit_tail():
    # one colon but tail is not all-digits -> treated as a bare host
    assert _split_host_port("router:abc") == ("router:abc", None)


def test_split_host_port_empty_head():
    # one colon but empty head -> bare host
    assert _split_host_port(":8080") == (":8080", None)


def test_split_host_port_no_colon():
    assert _split_host_port("router") == ("router", None)


def test_split_host_port_two_colons():
    # bare IPv6-ish value with >1 colon -> left as a bare host
    assert _split_host_port("fe80::1") == ("fe80::1", None)


# --- _is_ip_literal --------------------------------------------------------


def test_is_ip_literal_true_ipv4():
    assert _is_ip_literal("10.0.0.1") is True


def test_is_ip_literal_true_ipv6():
    assert _is_ip_literal("fe80::1") is True


def test_is_ip_literal_false():
    assert _is_ip_literal("router") is False


# --- SystemResolver (monkeypatched getaddrinfo) ----------------------------


def _addrinfo(addr: str):
    # getaddrinfo returns 5-tuples; only index [4][0] (the address) is used.
    return (socket.AF_INET, socket.SOCK_STREAM, 0, "", (addr, 0))


def test_system_resolver_returns_sorted_unique(monkeypatch):
    def fake_getaddrinfo(host, port):
        assert host == "gx10"
        return [_addrinfo("10.0.0.2"), _addrinfo("10.0.0.1"), _addrinfo("10.0.0.1")]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert SystemResolver().resolve("gx10") == ["10.0.0.1", "10.0.0.2"]


def test_system_resolver_gaierror_raises_nameresolutionerror(monkeypatch):
    def fake_getaddrinfo(host, port):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(NameResolutionError):
        SystemResolver().resolve("nonexistent")


def test_system_resolver_empty_result_raises(monkeypatch):
    # getaddrinfo succeeds but yields no addresses -> NameResolutionError
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [])
    with pytest.raises(NameResolutionError):
        SystemResolver().resolve("gx10")


# --- validate_endpoint -----------------------------------------------------


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_validate_endpoint_empty_raises_configerror(value):
    resolver = FakeResolver(["10.0.0.1"])
    with pytest.raises(ConfigError):
        validate_endpoint(value, resolver)
    assert resolver.calls == []  # never reached the resolver


def test_validate_endpoint_raw_ipv4_rejected():
    resolver = FakeResolver(["10.0.0.1"])
    with pytest.raises(RawIPError):
        validate_endpoint("10.0.0.5", resolver)
    assert resolver.calls == []


def test_validate_endpoint_raw_ipv4_with_port_rejected():
    # host part is an IP literal after splitting the :port -> RawIPError
    resolver = FakeResolver(["10.0.0.1"])
    with pytest.raises(RawIPError):
        validate_endpoint("10.0.0.5:8080", resolver)
    assert resolver.calls == []


def test_validate_endpoint_bare_ipv6_rejected():
    # >1 colon, stays a bare host, which is an IP literal -> RawIPError
    resolver = FakeResolver(["10.0.0.1"])
    with pytest.raises(RawIPError):
        validate_endpoint("fe80::1", resolver)
    assert resolver.calls == []


def test_validate_endpoint_valid_name_no_port():
    resolver = FakeResolver(["10.0.0.7", "10.0.0.8"])
    result = validate_endpoint("gx10", resolver)
    assert result == EndpointResolution(name="gx10", port=None, addresses=("10.0.0.7", "10.0.0.8"))
    assert resolver.calls == ["gx10"]


def test_validate_endpoint_valid_name_with_port():
    resolver = FakeResolver(["10.0.0.7"])
    result = validate_endpoint("gx10:8443", resolver)
    assert result == EndpointResolution(name="gx10", port=8443, addresses=("10.0.0.7",))
    assert resolver.calls == ["gx10"]


def test_validate_endpoint_resolver_returns_empty_raises():
    # resolver double returns [] -> the post-resolve guard fires
    resolver = FakeResolver([])
    with pytest.raises(NameResolutionError):
        validate_endpoint("gx10", resolver)
    assert resolver.calls == ["gx10"]


def test_validate_endpoint_resolver_raises_propagates():
    boom = NameResolutionError("name does not resolve: 'gx10'")
    resolver = FakeResolver(raises=boom)
    with pytest.raises(NameResolutionError) as exc:
        validate_endpoint("gx10", resolver)
    assert exc.value is boom
    assert resolver.calls == ["gx10"]


def test_validate_endpoint_out_of_range_port_raises_configerror():
    # name:port where port parses but is out of range -> ConfigError from _parse_port
    resolver = FakeResolver(["10.0.0.1"])
    with pytest.raises(ConfigError):
        validate_endpoint("router:99999", resolver)
    assert resolver.calls == []
