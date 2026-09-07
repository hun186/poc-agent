from dataclasses import dataclass
from datetime import datetime
import secrets

CONTROL_DOMAIN = "requirement-report-v1"

@dataclass(frozen=True)
class LeaseProof:
    control_domain: str
    owner_id: str
    lease_token: str
    fencing_generation: int
    expires_at: datetime

    def __post_init__(self):
        if self.control_domain != CONTROL_DOMAIN or not self.owner_id or len(self.owner_id) > 128:
            raise ValueError("lease_invalid")
        if len(self.lease_token) != 64 or any(c not in "0123456789abcdef" for c in self.lease_token):
            raise ValueError("lease_invalid")
        if not 0 < self.fencing_generation < 2**63:
            raise ValueError("lease_invalid")

def new_lease_token() -> str:
    return secrets.token_hex(32)
