from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AuthPrincipal:
    kind: Literal["user", "service"]
    subject: str
    role: str | None
    scopes: frozenset[str]
    credential_id: str | None = None

    @property
    def principal_id(self) -> str:
        return f"{self.kind}:{self.subject}"

