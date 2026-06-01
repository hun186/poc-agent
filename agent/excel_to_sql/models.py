from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class RowResult:
    row_no: int
    hash_value: str
    status: str
    message: str = ""
    row_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileResult:
    file_path: Path
    success: int = 0
    duplicate: int = 0
    failed: int = 0
    skipped: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.failed == 0
