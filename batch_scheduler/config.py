from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass(frozen=True, repr=False)
class BatchSchedulerConfig:
    api_base: str
    service_key: str = field(repr=False)
    db_path: Path = Path('.batch_scheduler/scheduler.sqlite3')
    output_root: Path = Path('.batch_scheduler/output')
    poll_seconds: float = 2.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    max_retries: int = 3
    def __post_init__(self):
        object.__setattr__(self, 'api_base', self.api_base.rstrip('/'))
        if not self.api_base: raise ValueError('api_base is required')
        if min(self.poll_seconds,self.connect_timeout,self.read_timeout) <= 0 or self.max_retries < 0: raise ValueError('timeouts/poll must be positive and retries non-negative')
    def __repr__(self): return f"BatchSchedulerConfig(api_base={self.api_base!r}, db_path={self.db_path!r}, output_root={self.output_root!r})"
    @classmethod
    def from_env(cls, *, require_key=True):
        key=os.getenv('SRA_BATCH_SERVICE_KEY','')
        if require_key and not key: raise ValueError('SRA_BATCH_SERVICE_KEY is required')
        return cls(os.getenv('SRA_API_BASE','http://127.0.0.1:9002'),key,Path(os.getenv('SRA_BATCH_DB_PATH','.batch_scheduler/scheduler.sqlite3')),Path(os.getenv('SRA_BATCH_OUTPUT_ROOT','.batch_scheduler/output')),float(os.getenv('SRA_BATCH_POLL_SECONDS','2')),float(os.getenv('SRA_BATCH_HTTP_CONNECT_TIMEOUT','10')),float(os.getenv('SRA_BATCH_HTTP_READ_TIMEOUT','30')),int(os.getenv('SRA_BATCH_MAX_RETRIES','3')))
