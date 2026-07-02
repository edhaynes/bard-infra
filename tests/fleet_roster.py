"""Single source of truth for the bardnet fleet roster (PLAN_bardnet_fleet_test, T1.1).

The six physical devices from ``shared-rules/connectivity.md`` (2026-07-01), as
``FleetDevice(device_id, label, platform, reachable_default)`` tuples. This module
is imported by BOTH the hermetic test (``tests/test_bardnet_fleet.py``) and the
narrated smoke run (``scripts/smoke_bardnet_fleet.py``) so the two drive the
*identical* roster — one place to edit when the fleet changes.

``reachable_default`` records each box's real state: ``beagle`` is DOWN (USB-gadget
failure) and ``barney`` is unpowered, so both are the deliberate ``offline`` cases
the ping contract must report as a clean 200 (a member with no live link is listed
``offline``, not an error). The other four are reachable by default.
"""

from __future__ import annotations

from typing import NamedTuple


class FleetDevice(NamedTuple):
    """One device in the bardnet fleet roster."""

    device_id: str
    label: str
    platform: str
    reachable_default: bool


#: The fleet, in onboarding order (also the order membership is asserted in).
FLEET_ROSTER: tuple[FleetDevice, ...] = (
    FleetDevice("dev-mac", "Mac", "macOS arm64", True),
    FleetDevice("gx10", "Gladius", "Ubuntu 24.04 aarch64", True),
    FleetDevice("bullfrog", "Bullfrog", "Ubuntu 26.04 x86_64", True),
    FleetDevice("snoopy", "Snoopy", "Debian aarch64 (BeaglePlay)", True),
    FleetDevice("beagle", "Beagle", "Debian aarch64 (BeaglePlay) — DOWN", False),
    FleetDevice("barney", "Barney", "Debian aarch64 (BeaglePlay) — unpowered", False),
)
