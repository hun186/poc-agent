from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

@dataclass(frozen=True)
class RequirementHandoffConfig:
    api_base_url: str
    logical_principal: str
    credential_provider: Callable[[str], str]
    output_root: Path
    connect_timeout: float = 5
    read_timeout: float = 60
    poll_interval: float = 2
    heartbeat_interval: float = 10
    lease_duration: float = 45
    request_retries: int = 3
    max_backoff: float = 5
    batch_size: int = 20
    allow_insecure_localhost: bool = False

    def __post_init__(self):
        parsed = urlparse(self.api_base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (self.allow_insecure_localhost and local): raise ValueError("api_url_invalid")
        if not self.logical_principal or not callable(self.credential_provider): raise ValueError("credential_config_invalid")
        if min(self.connect_timeout, self.read_timeout, self.poll_interval, self.heartbeat_interval, self.lease_duration) <= 0: raise ValueError("timing_invalid")
        if self.heartbeat_interval >= self.lease_duration / 3: raise ValueError("lease_timing_invalid")
        if not 1 <= self.request_retries <= 10 or not 1 <= self.batch_size <= 100 or self.max_backoff <= 0: raise ValueError("bounds_invalid")
