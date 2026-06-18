"""Element 4 — a member endpoint that holds the current epoch key and opens
messages it is authorized for.
"""

from __future__ import annotations

from dataclasses import dataclass

from trust.group import Ciphertext, NotAuthorized, Welcome
from trust.identity import Identity


@dataclass
class Member:
    identity: Identity
    group_name: str | None = None
    epoch: int = -1
    _secret: str | None = None

    def accept_welcome(self, welcome: Welcome) -> None:
        self.group_name = welcome.group
        self.epoch = welcome.epoch
        self._secret = welcome.epoch_secret

    @property
    def has_key(self) -> bool:
        return self._secret is not None

    def open(self, ct: Ciphertext) -> tuple[str, str]:
        # Forward secrecy / lock-out: must hold the secret for the message's epoch.
        if self._secret is None or self.epoch != ct.epoch:
            raise NotAuthorized("no key for this epoch")
        return ct.sender, ct.blob
