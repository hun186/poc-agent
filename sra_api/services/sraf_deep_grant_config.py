"""Immutable deep owner grants and capacity; no auth or runtime imports."""
from dataclasses import dataclass
import re


class DeepScopeDenied(ValueError):
    """Fixed authorization denial, no private information."""


_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")


@dataclass(frozen=True, repr=False)
class DeepOwnerGrant:
    owner_id: str
    account_created_at: str
    indexes: tuple[str, ...]

    def __post_init__(self):
        if (type(self.owner_id) is not str or not 1 <= len(self.owner_id) <= 64
                or self.owner_id != self.owner_id.strip()
                or type(self.account_created_at) is not str
                or not 1 <= len(self.account_created_at) <= 80
                or self.account_created_at != self.account_created_at.strip()
                or type(self.indexes) is not tuple or not 1 <= len(self.indexes) <= 8
                or any(type(i) is not str or not _INDEX.fullmatch(i)
                       or ".." in i for i in self.indexes)
                or len(set(self.indexes)) != len(self.indexes)):
            raise DeepScopeDenied("deep_owner_grant_invalid")


@dataclass(frozen=True, repr=False)
class DeepGrantConfig:
    grants: tuple[DeepOwnerGrant, ...]
    max_active_jobs: int

    def __post_init__(self):
        if (type(self.grants) is not tuple or not 1 <= len(self.grants) <= 256
                or any(type(g) is not DeepOwnerGrant for g in self.grants)
                or len({g.owner_id for g in self.grants}) != len(self.grants)
                or type(self.max_active_jobs) is not int
                or not 1 <= self.max_active_jobs <= 1000):
            raise DeepScopeDenied("deep_policy_invalid")
