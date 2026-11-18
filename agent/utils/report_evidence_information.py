"""Count-only information-quantity warning for report Evidence passed to the LLM.

This is a mechanical character/row-count signal, NOT a factual correctness,
completeness or recall judgment. It never rewrites or drops Evidence.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "sraf_report_evidence_information_v1"
MAX_ROWS = 500
MAX_NOTE_CHARS = 50_000
MAX_TOTAL_CHARS = 2_000_000
_DATE_ONLY = re.compile(r"\s*\d{4}(?:[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?)?\s*\Z")


def assess_report_evidence_information(rows: Any) -> dict[str, Any]:
    """Read only original LLM-visible notes; return only bounded numbers.

    Short does NOT necessarily mean false or unimportant. Warn, do not filter.
    """
    result: dict[str, Any] = {
        "schema": SCHEMA, "status": "not_assessed", "rows": 0,
        "total_visible_chars": 0, "short_notes": 0, "date_only_notes": 0,
    }
    if type(rows) is not list or len(rows) > MAX_ROWS:
        return result
    seen: set[int] = set()
    total = short = date_only = 0
    for row in rows:
        if type(row) is not dict:
            return result
        ref = row.get("ref_no")
        note = row.get("note")
        if type(ref) is not int or not 0 < ref <= 1_000_000 or ref in seen:
            return result
        if type(note) is not str or len(note) > MAX_NOTE_CHARS:
            return result
        seen.add(ref)
        visible = "".join(note.split())
        total += len(visible)
        if total > MAX_TOTAL_CHARS:
            return result
        if len(visible) < 32:
            short += 1
        if _DATE_ONLY.fullmatch(note):
            date_only += 1
    result.update(
        rows=len(rows), total_visible_chars=total,
        short_notes=short, date_only_notes=date_only,
        status=("no_evidence" if not rows else
                "limited_text" if date_only == len(rows) or
                (len(rows) <= 2 and total < 120) or
                (len(rows) <= 4 and short == len(rows))
                else "measured_only"),
    )
    return result


def evidence_information_notice(info: dict[str, Any]) -> str | None:
    """No false 'sufficient' verdict; caller decides how to present warning."""
    if info.get("status") == "limited_text":
        return (
            "⚠️ 證據資訊量提醒：本次提供給報告模型的 Evidence 片段較少或文字過短，"
            "可能不足以支撐完整事件背景、因果關係或定量結論。"
            "以下僅可作為現有片段的初步整理，請核對原文及補充必要資料。"
        )
    if info.get("status") == "not_assessed":
        return "⚠️ 本次未能確認 Evidence 資訊量；請核對原始來源。"
    return None
