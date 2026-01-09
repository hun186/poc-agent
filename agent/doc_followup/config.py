# agent/doc_followup/config.py
from __future__ import annotations
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class DocFollowupConfig:
    max_total_chars: int = 26000
    max_docs: int = 5

    # planner/llm timeout
    planner_timeout_sec: float = 60.0
    followup_timeout_sec: float = 180.0

    # uuid candidate extraction
    max_uuid_candidates: int = 3

    # UI hint chunks (for prompt examples)
    @property
    def ex_1(self) -> int:
        return self.max_total_chars

    @property
    def ex_2_start(self) -> int:
        return self.max_total_chars + 1

    @property
    def ex_2_end(self) -> int:
        return self.max_total_chars * 2

    @property
    def ex_3_start(self) -> int:
        return self.max_total_chars * 2 + 1

    @property
    def ex_3_end(self) -> int:
        return self.max_total_chars * 3


def load_doc_followup_config_from_env() -> DocFollowupConfig:
    """
    讀取環境變數，給 doc_followup 全套共用設定。
    """
    max_total = int(os.getenv("DOC_FOLLOWUP_MAX_TOTAL_CHARS", "26000"))
    max_docs = int(os.getenv("DOC_FOLLOWUP_MAX_DOCS", "5"))

    planner_timeout = float(os.getenv("DOC_FOLLOWUP_PLANNER_TIMEOUT", "60"))
    followup_timeout = float(os.getenv("DOC_FOLLOWUP_TIMEOUT", "180"))

    max_uuid_candidates = int(os.getenv("DOC_FOLLOWUP_MAX_UUID_CANDIDATES", "3"))

    # 防呆
    if max_total <= 0:
        max_total = 26000
    if max_docs <= 0:
        max_docs = 5
    if planner_timeout <= 0:
        planner_timeout = 60.0
    if followup_timeout <= 0:
        followup_timeout = 180.0
    if max_uuid_candidates <= 0:
        max_uuid_candidates = 3

    return DocFollowupConfig(
        max_total_chars=max_total,
        max_docs=max_docs,
        planner_timeout_sec=planner_timeout,
        followup_timeout_sec=followup_timeout,
        max_uuid_candidates=max_uuid_candidates,
    )
