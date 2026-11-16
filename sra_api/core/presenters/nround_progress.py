"""Strict count-only N-round progress presentation for Word and OpenWebUI.

Only whitelisted numerics/booleans and fixed reason codes may leave this
module. Never echo the original question, optional LLM terms, index/ES IDs,
date, snippet content, hashes, runtime exception text or a job identifier.

This is a *presentation contract*, not a live N-round execution or persistence
feature. It may be attached to evidence_usage after a real, trusted Job has
produced a canonical coordinator.safe_progress() snapshot.
"""
from __future__ import annotations

from typing import Any

SCHEMA = "sraf_nround_coordinator_progress_v1"
_PHASES = frozenset(("CREATED", "SEARCHING", "ASSESSING",
                     "ASSESSED", "PLANNING", "TERMINAL"))
_TERMINATIONS = {
    "NONE": "尚未結束",
    "SUFFICIENT": "可信評估認定資料已足夠",
    "CANCELLED": "操作取消；不再核准新輪次",
    "ROUND_BUDGET_EXHAUSTED": "已達輪數上限",
    "RESOURCE_BUDGET_EXHAUSTED": "搜尋次數、時間或模型預算已用盡",
    "SAME_PLAN_SEARCH_INCOMPLETE": "本輪檢索結果不完整；未繼續擴充",
    "REQUEST_LEVEL_ASSESSMENT_REQUIRED": "缺少整體檢索評估；未繼續擴充",
    "EVIDENCE_VALIDATION_FAILED": "來源或證據驗證失敗；已停止",
    "PLANNER_FAILED_CLOSED": "策略規劃異常；已保守停止",
    "DIMINISHING_RETURNS": "連續輪次沒有新增合格證據",
    "NO_EXPECTED_GAIN": "沒有預期新增研究價值",
    "USER_KEYWORDS_LOCKED": "使用者鎖定關鍵字；不自行變更",
    "NO_NEW_QUERY_PLAN": "無可執行的新搜尋策略",
    "DATE_PARSE_SUSPECTED": "日期條件需要重新檢查",
    "INVALID_CONTEXT": "檢索內容契約無效",
    "INCONSISTENT_ROUND_HISTORY": "輪次歷程不一致",
    "PLANNER_STOPPED": "策略規劃未批准繼續",
    "UNTRUSTED_NEXT_ROUND_SCOPE": "下一輪策略觸及不可信任的範圍",
    "LATE_BUDGET_EXHAUSTED": "策略運算後已超出檢索截止時間",
    "STALE_ROUND_HISTORY": "上一輪歷程過期，未進行重複規劃",
    "NO_NEW_STRATEGY": "沒有新的策略",
}
_REPORT_READY_REASONS = frozenset((
    "SUFFICIENT", "ROUND_BUDGET_EXHAUSTED", "RESOURCE_BUDGET_EXHAUSTED",
    "DIMINISHING_RETURNS", "NO_EXPECTED_GAIN", "NO_NEW_QUERY_PLAN",
    "USER_KEYWORDS_LOCKED",
))
_ROW_COUNTS = ("candidate_sources", "parser_output", "validated_rows",
               "fallback", "verified_in_round", "new_verified",
               "new_sources", "cumulative_verified", "cumulative_sources")


def _count(v: Any, maximum: int) -> int | None:
    if type(v) is int and 0 <= v <= maximum:
        return v
    return None


def safe_nround_progress(raw: Any) -> dict[str, Any]:
    """Validate canonical count-only state and derive a fresh clean object."""
    if type(raw) is not dict or raw.get("schema") != SCHEMA:
        return {}
    phase, reason = raw.get("phase"), raw.get("termination")
    if (type(phase) is not str or type(reason) is not str
            or phase not in _PHASES or reason not in _TERMINATIONS):
        return {}
    if (raw.get("live_es") != "NOT_EXECUTED_BY_COORDINATOR"
            or raw.get("report_job") != "NOT_INTEGRATED"
            or raw.get("checkpoint_resume") != "NOT_IMPLEMENTED"):
        return {}
    current = _count(raw.get("round"), 8)
    completed = _count(raw.get("completed_rounds"), 8)
    es_slots = _count(raw.get("es_calls_admitted_this_round"), 1000)
    report_ready = raw.get("ready_for_external_report_generation")
    if (None in (current, completed, es_slots)
            or type(report_ready) is not bool
            or not completed <= current <= completed + 1
            or (phase == "CREATED" and (current != 0 or completed != 0))
            or (phase in ("ASSESSED", "PLANNING") and current != completed)
            or (phase in ("SEARCHING", "ASSESSING") and
                current != completed + 1)
            or (phase == "TERMINAL" and reason == "NONE")
            or (phase != "TERMINAL" and reason != "NONE")):
        return {}
    rows = raw.get("canonical_evidence_history")
    if type(rows) not in (list, tuple) or len(rows) != completed:
        return {}
    clean_rows = []
    previous_evidence = previous_sources = 0
    for i, item in enumerate(rows, 1):
        if type(item) is not dict or _count(item.get("round"), 8) != i:
            return {}
        nums = {key: _count(item.get(key), 16384) for key in _ROW_COUNTS}
        if any(value is None for value in nums.values()):
            return {}
        complete, attested = item.get("complete"), item.get("request_wide_attested")
        if type(complete) is not bool or type(attested) is not bool:
            return {}
        if (nums["candidate_sources"] > 1000
                or nums["parser_output"] > 4096
                or nums["validated_rows"] > nums["parser_output"]
                or nums["fallback"] != nums["parser_output"] - nums["validated_rows"]
                or nums["verified_in_round"] > nums["validated_rows"]
                or nums["new_verified"] > nums["verified_in_round"]
                or nums["new_sources"] > nums["candidate_sources"]
                or nums["cumulative_verified"] !=
                    previous_evidence + nums["new_verified"]
                or nums["cumulative_sources"] !=
                    previous_sources + nums["new_sources"]
                or nums["cumulative_sources"] > nums["cumulative_verified"]):
            return {}
        previous_evidence = nums["cumulative_verified"]
        previous_sources = nums["cumulative_sources"]
        clean_rows.append({
            "round": i, **nums, "complete": complete,
            "request_wide_attested": attested,
        })
    if report_ready and (
        phase != "TERMINAL" or reason not in _REPORT_READY_REASONS
        or current != completed or completed == 0
        or not all(x["complete"] and x["request_wide_attested"]
                   for x in clean_rows)
    ):
        return {}
    if completed and any(not row["complete"] for row in clean_rows[:-1]):
        return {}
    return {
        "schema": SCHEMA, "phase": phase, "termination": reason,
        "round": current, "completed_rounds": completed,
        "es_calls_admitted_this_round": es_slots,
        "ready_for_external_report_generation": report_ready,
        "canonical_evidence_history": clean_rows,
        "live_es": "NOT_EXECUTED_BY_COORDINATOR",
        "report_job": "NOT_INTEGRATED",
        "checkpoint_resume": "NOT_IMPLEMENTED",
    }


def nround_progress_rows(raw: Any) -> list[tuple[str, str]]:
    """Short Chinese facts, suitable for shared DOCX + Markdown data-agent UI."""
    clean = safe_nround_progress(raw)
    if not clean:
        return []
    phase = clean["phase"]
    phase_label = {
        "CREATED": "尚未開始", "SEARCHING": "檢索中（僅計入已核准請求）",
        "ASSESSING": "證據驗證中", "ASSESSED": "本輪證據已計數",
        "PLANNING": "規劃下一輪策略中", "TERMINAL": "已終止",
    }[phase]
    lines = [
        ("多輪智慧檢索歷程", f"{phase_label}；累計完成 "
                           f"{clean['completed_rounds']} 輪；目前第 "
                           f"{clean['round']} 輪；本輪已核准 ES "
                           f"{clean['es_calls_admitted_this_round']} 次（不代表實際請求成功）"),
    ]
    for row in clean["canonical_evidence_history"]:
        completed = ("整輪完整／可信評估已確認" if
                     row["complete"] and row["request_wide_attested"] else
                     "尚未確認整輪完整性")
        lines.append((
            f"第 {row['round']} 輪 Evidence",
            f"ES 候選來源 {row['candidate_sources']} 篇；"
            f"Parser 輸出 {row['parser_output']} 段，其中 "
            f"{row['validated_rows']} 段符合本層日期／主題條件，"
            f"{row['fallback']} 段未列為合格證據；"
            f"本輪去重合格 {row['verified_in_round']} 段，"
            f"真正新增 {row['new_verified']} 段／新增來源 {row['new_sources']} 篇；"
            f"累計合格 {row['cumulative_verified']} 段／"
            f"累計有效來源 {row['cumulative_sources']} 篇；{completed}",
        ))
    if phase == "TERMINAL":
        lines.append(("多輪檢索停止原因", _TERMINATIONS[clean["termination"]]))
    lines.append((
        "多輪報告生成狀態",
        ("本層已達外部報告交接條件；不代表 Word 已產出或通過驗收" if
         clean["ready_for_external_report_generation"] else
         "尚未具備本層外部報告交接條件；不代表 Word 已產出"),
    ))
    lines.append((
        "多輪資料判讀限制",
        "上述僅為程式內的模擬／契約階段計數；不是實際 ES 召回率、"
        "人工語義相關度、LLM Token 消耗或最終 Word 引用數。"
        "目前未接正式 Report Job、未實作持久化恢復。",
    ))
    return lines
