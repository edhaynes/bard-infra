"""Hermetic contract tests for ``validate_endpoint`` and its helpers.

No network: a ``FakeResolver`` test double (dependency injection) stands in for
the OS resolver, mapping names to addresses and modelling the empty-result and
raise variants. Exercises every branch of ``validate_endpoint``,
``_split_host_port``, ``_parse_port``, and ``_is_ip_literal``.
"""

from __future__ import annotations

import pytest

from bard_infra.nameres.resolver import NameResolutionError, Resolver
from bard_infra.nameres.validator import (
    EndpointResolution,
    RawIPError,
    _is_ip_literal,
    _parse_port,
    _split_host_port,
    validate_endpoint,
)


class FakeResolver(Resolver):
    """Injectable resolver double: a name->addresses map, with opt-in failure.

    - Names in ``mapping`` resolve to their listed addresses.
    - Names in ``empty`` resolve to ``[]`` (no addresses).
    - Any other name raises ``NameResolutionError`` (models a miss).
    """

    def __init__(
        self,
        mapping: dict[str, list[str]] | None = None,
        empty: set[str] | None = None,
    ) -> None:
        self.mapping = mapping or {}
        self.empty = empty or set()
        self.calls: list[str] = []

    def resolve(self, host: str) -> list[str]:
        self.calls.append(host)
        if host in self.empty:
            return []
        if host in self.mapping:
            return self.mapping[host]
        raise NameResolutionError(f"name does not resolve: {host!r}")


# --- validate_endpoint branches -------------------------------------------


def test_empty_string_raises_value_error() -> None:
    """(a) Empty input is a configuration error."""
    with pytest.raises(ValueError, match="empty endpoint value"):
        validate_endpoint("", FakeResolver())


def test_whitespace_only_raises_value_error() -> None:
    """(b) Whitespace-only input strips to empty -> ValueError."""
    with pytest.raises(ValueError, match="empty endpoint value"):
        validate_endpoint("   ", FakeResolver())


def test_raw_ipv4_host_raises_rawiperror() -> None:
    """(c) A bare IPv4 literal is rejected before any resolution."""
    resolver = FakeResolver()
    with pytest.raises(RawIPError, match="raw IP"):
        validate_endpoint("10.0.0.5", resolver)
    assert resolver.calls == []  # rejected before resolve()


def test_raw_ipv4_with_port_raises_rawiperror() -> None:
    """(d) IPv4:port splits into an IP host, still rejected as raw IP."""
    resolver = FakeResolver()
    with pytest.raises(RawIPError, match="raw IP"):
        validate_endpoint("10.0.0.5:8080", resolver)
    assert resolver.calls == []


def test_bare_ipv6_literal_raises_rawiperror() -> None:
    """(e) Bare IPv6 (two colons -> not host:port) is a raw IP literal."""
    resolver = FakeResolver()
    with pytest.raises(RawIPError, match="raw IP"):
        validate_endpoint("fe80::1", resolver)
    assert resolver.calls == []


def test_valid_name_resolves_with_no_port() -> None:
    """(f) A resolvable name with no port -> port is None."""
    resolver = FakeResolver({"router": ["100.64.0.1"]})
    result = validate_endpoint("router", resolver)
    assert result == EndpointResolution(
        name="router", port=None, addresses=("100.64.0.1",)
    )
    assert resolver.calls == ["router"]


def test_valid_name_with_port() -> None:
    """(g) ``name:port`` parses the port and resolves the head."""
    resolver = FakeResolver({"router": ["100.64.0.1", "100.64.0.2"]})
    result = validate_endpoint("router:8080", resolver)
    assert result.name == "router"
    assert result.port == 8080
    assert result.addresses == ("100.64.0.1", "100.64.0.2")
    assert resolver.calls == ["router"]


def test_name_resolving_to_empty_raises_name_resolution_error() -> None:
    """(h) Resolver returns ``[]`` -> NameResolutionError (no addresses)."""
    resolver = FakeResolver(empty={"ghost"})
    with pytest.raises(NameResolutionError, match="no addresses"):
        validate_endpoint("ghost", resolver)
    assert resolver.calls == ["ghost"]


def test_name_that_resolver_raises_on_propagates() -> None:
    """(i) Resolver raising NameResolutionError propagates unchanged."""
    resolver = FakeResolver()  # unknown name -> raises
    with pytest.raises(NameResolutionError, match="does not resolve"):
        validate_endpoint("unknown-host", resolver)
    assert resolver.calls == ["unknown-host"]


# --- _split_host_port branches --------------------------------------------


def test_split_one_colon_valid_port() -> None:
    """count(':')==1, truthy head, all-digit tail -> (head, port)."""
    assert _split_host_port("router:8080") == ("router", 8080)


def test_split_one_colon_non_digit_tail_is_bare_host() -> None:
    """count(':')==1 but tail not all digits -> whole value, no port.

    Verified against source: 'router:abc' has head='router', tail='abc'
    which is not isdigit(), so the if-body is skipped and the bare value is
    returned. validate_endpoint then resolves the literal 'router:abc'.
    """
    assert _split_host_port("router:abc") == ("router:abc", None)


def test_split_one_colon_empty_head_is_bare_host() -> None:
    """count(':')==1 but empty head (':8080') -> whole value, no port."""
    assert _split_host_port(":8080") == (":8080", None)


def test_split_zero_colons_is_bare_host() -> None:
    """count(':')!=1 (0 colons) -> whole value, no port."""
    assert _split_host_port("router") == ("router", None)


def test_split_two_colons_is_bare_host() -> None:
    """count(':')!=1 (2 colons, e.g. bare IPv6) -> whole value, no port."""
    assert _split_host_port("fe80::1") == ("fe80::1", None)


def test_non_digit_tail_resolves_as_literal_name() -> None:
    """End-to-end of the 'router:abc' path: resolved as a literal name."""
    resolver = FakeResolver({"router:abc": ["100.64.0.9"]})
    result = validate_endpoint("router:abc", resolver)
    assert result.name == "router:abc"
    assert result.port is None
    assert result.addresses == ("100.64.0.9",)
    assert resolver.calls == ["router:abc"]


# --- _parse_port branches -------------------------------------------------


def test_parse_port_valid() -> None:
    """In-range port returns the int."""
    assert _parse_port("8080") == 8080


def test_parse_port_out_of_range_propagates() -> None:
    """Out-of-range port (>65535) raises ValueError, propagated by caller."""
    resolver = FakeResolver({"router": ["100.64.0.1"]})
    with pytest.raises(ValueError, match="port out of range"):
        validate_endpoint("router:99999", resolver)
    # Rejected during parse, before the resolver is ever consulted.
    assert resolver.calls == []


# --- _is_ip_literal branches ----------------------------------------------


def test_is_ip_literal_true_for_ip() -> None:
    """True path: an IP literal."""
    assert _is_ip_literal("10.0.0.5") is True


def test_is_ip_literal_false_for_name() -> None:
    """False path: a logical name is not an IP literal."""
    assert _is_ip_literal("router") is False


# --- contract done-signal: name survives IP churn -------------------------


def test_name_survives_ip_churn() -> None:
    """Done-signal: same name, new address, still accepted -> new address.

    Models a node reimage/DHCP reassignment: the resolver returns a different
    address for the same fixed name with no config edit.
    """
    resolver = FakeResolver({"gx10": ["100.64.0.10"]})
    before = validate_endpoint("gx10", resolver)
    assert before.addresses == ("100.64.0.10",)

    resolver.mapping["gx10"] = ["100.64.0.99"]  # node moved
    after = validate_endpoint("gx10", resolver)
    assert after.addresses == ("100.64.0.99",)
    assert after.name == "gx10"
