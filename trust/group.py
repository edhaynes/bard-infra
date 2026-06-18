"""Element 3 — the workgroup group session (MLS group) + epoch key.

LEVEL 0 stub: membership set + an epoch counter + a per-epoch secret that
rotates on every add/remove (the MLS re-key property). Confidentiality is
modeled by epoch-secret *possession*: a message sealed at epoch N can only be
opened by a holder of epoch N's secret. LEVEL 1: a real OpenMLS group (TreeKEM,
HPKE, AEAD).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from trust.identity import KeyPackage


class NotAuthorized(Exception):
    """Raised when a non-member seals or a stale-epoch holder opens."""


@dataclass(frozen=True)
class Welcome:
    """Delivered to a member after an Add/Commit; carries the current epoch key."""

    group: str
    epoch: int
    epoch_secret: str


@dataclass(frozen=True)
class Ciphertext:
    group: str
    epoch: int
    sender: str
    blob: str  # LEVEL 0: plaintext carried; access gated by epoch possession.


@dataclass
class GroupSession:
    name: str
    epoch: int = 0
    members: dict[str, str] = field(default_factory=dict)  # pubkey -> init_key
    _epoch_secret: str = field(default_factory=lambda: secrets.token_hex(16))

    def _rekey(self) -> None:
        self.epoch += 1
        self._epoch_secret = secrets.token_hex(16)

    def add(self, kp: KeyPackage) -> Welcome:
        self.members[kp.identity_pubkey] = kp.init_key
        self._rekey()
        return self.current_welcome()

    def remove(self, pubkey: str) -> Welcome:
        self.members.pop(pubkey, None)
        self._rekey()
        return self.current_welcome()

    def current_welcome(self) -> Welcome:
        return Welcome(self.name, self.epoch, self._epoch_secret)

    def seal(self, sender_pubkey: str, plaintext: str) -> Ciphertext:
        if sender_pubkey not in self.members:
            raise NotAuthorized(f"{sender_pubkey} is not a member of {self.name}")
        return Ciphertext(self.name, self.epoch, sender_pubkey, plaintext)
