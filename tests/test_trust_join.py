"""Zero-trust client-join workflow test (Level 0 — see trust/__init__.py).

Walks the full onboarding sequence and asserts the security properties:
  bootstrap -> join request -> attestation -> manager approval (gate) ->
  re-key + key delivery -> send/receive with attribution -> revoke -> lock-out.
"""

from __future__ import annotations

import pytest

from trust.attestation import attest
from trust.control_plane import Manager
from trust.group import NotAuthorized
from trust.identity import Identity
from trust.member import Member


def _new_workgroup() -> tuple[Manager, Member]:
    alice = Identity.generate("alice")  # manager
    return Manager("wg-eng", alice), Member(alice)


def test_happy_path_join_send_and_revoke():
    manager, _ = _new_workgroup()
    alice = manager.manager_member

    # 1-2. Bob bootstraps identity + key package, gets a device attestation.
    bob_id = Identity.generate("bob")
    bob = Member(bob_id)
    req = Manager.request_join(attest(bob_id), bob_id.key_package())
    assert not bob.has_key  # zero-trust: no key before approval

    # 3-6. Manager approves (gate 1), group re-keys, Bob receives the epoch key.
    epoch_before = manager.group.epoch
    assert manager.approve(req, bob) is True
    assert bob.has_key
    assert manager.group.epoch > epoch_before  # add advanced the epoch

    # 7-8. Bob sends a message to the group; Alice opens it with attribution.
    ct = manager.group.seal(bob_id.public_key, "deploy at 5pm")
    sender, text = alice.open(ct)
    assert (sender, text) == (bob_id.public_key, "deploy at 5pm")

    # 9-10. Manager revokes Bob -> re-key -> Bob is locked out of new traffic.
    manager.revoke(bob_id.public_key)
    assert bob_id.public_key in manager.revoked
    fresh = manager.group.seal(alice.identity.public_key, "post-revoke secret")
    with pytest.raises(NotAuthorized):
        bob.open(fresh)  # stale epoch -> no key
    with pytest.raises(NotAuthorized):
        manager.group.seal(bob_id.public_key, "i'm still here")  # not a member


def test_unapproved_client_never_gets_a_key():
    manager, _ = _new_workgroup()
    carol = Member(Identity.generate("carol"))
    # No approve() call -> never receives a Welcome.
    assert not carol.has_key


def test_invalid_attestation_is_rejected():
    manager, _ = _new_workgroup()
    mallory_id = Identity.generate("mallory")
    mallory = Member(mallory_id)
    req = Manager.request_join(attest(mallory_id, valid=False), mallory_id.key_package())
    assert manager.approve(req, mallory) is False
    assert not mallory.has_key


def test_revoked_identity_cannot_rejoin():
    manager, _ = _new_workgroup()
    bob_id = Identity.generate("bob")
    bob = Member(bob_id)
    assert manager.approve(Manager.request_join(attest(bob_id), bob_id.key_package()), bob)
    manager.revoke(bob_id.public_key)
    # A revoked identity is refused even with a valid attestation.
    again = Member(bob_id)
    assert (
        manager.approve(Manager.request_join(attest(bob_id), bob_id.key_package()), again) is False
    )
