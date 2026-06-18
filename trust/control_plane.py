"""Element 5 — the workgroup manager / control plane (federated, per §13 D3).

Holds the group, enforces the two approval gates, distributes epoch keys on
re-key, and maintains the revocation list. LEVEL 1: this is where OpenMLS
Add/Remove/Commit + the real attestation verifier live.
"""

from __future__ import annotations

from dataclasses import dataclass

from trust.attestation import Attestation, verify_attestation
from trust.group import GroupSession, Welcome
from trust.identity import Identity, KeyPackage
from trust.member import Member


@dataclass(frozen=True)
class JoinRequest:
    attestation: Attestation
    key_package: KeyPackage


class Manager:
    def __init__(self, group_name: str, manager_identity: Identity):
        self.group = GroupSession(group_name)
        self.manager = manager_identity
        self.revoked: set[str] = set()
        self._members: list[Member] = []
        # The manager bootstraps the group as its first member.
        self.group.add(manager_identity.key_package())
        self.manager_member = Member(manager_identity)
        self.manager_member.accept_welcome(self.group.current_welcome())
        self._members.append(self.manager_member)

    @staticmethod
    def request_join(attestation: Attestation, key_package: KeyPackage) -> JoinRequest:
        return JoinRequest(attestation, key_package)

    def approve(self, request: JoinRequest, member: Member) -> bool:
        """Gate 1 (device approval). Verify attestation, Add, re-key, deliver."""
        if request.attestation.identity_pubkey in self.revoked:
            return False
        if not verify_attestation(request.attestation):
            return False
        welcome = self.group.add(request.key_package)
        self._distribute(welcome)
        member.accept_welcome(welcome)
        self._members.append(member)
        return True

    def revoke(self, pubkey: str) -> None:
        self.revoked.add(pubkey)
        welcome = self.group.remove(pubkey)
        self._members = [m for m in self._members if m.identity.public_key != pubkey]
        self._distribute(welcome)

    def _distribute(self, welcome: Welcome) -> None:
        for m in self._members:
            m.accept_welcome(welcome)
