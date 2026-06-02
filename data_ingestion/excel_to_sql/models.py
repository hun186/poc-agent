from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict


_ROW_NUMBER_RE = re.compile(r"Excel 第 \d+ 列")


def normalize_failure_message(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return "未提供錯誤訊息"
    text = _ROW_NUMBER_RE.sub("Excel 第 * 列", text)
    return text.split("；", 1)[0]


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
    failure_summary: Dict[str, int] = field(default_factory=dict)

    def record_failure(self, message: str) -> None:
        normalized_message = normalize_failure_message(message)
        self.failure_summary[normalized_message] = self.failure_summary.get(normalized_message, 0) + 1

    @property
    def ok(self) -> bool:
        return not self.error and self.failed == 0
