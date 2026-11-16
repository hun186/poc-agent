"""Only numeric Report Evidence statistics shared by Word and OpenWebUI."""
from __future__ import annotations
from typing import Any

SCHEMA = "sraf_report_evidence_usage_v1"
MODES = {"strong_first": "強證據優先（原模式）", "source_diverse": "來源多樣性（強證據優先）"}
REVIEW_SCHEMA = "sraf_report_evidence_review_v1"
REVIEW_MODES = {"off": "關閉", "shadow": "影子覆核（不排除證據）", "on": "正式覆核"}
REVIEW_STATUSES = {
    "disabled": "未執行（關閉）", "no_evidence": "無證據可覆核",
    "fallback": "降級保留全部證據", "shadow": "影子覆核完成",
    "applied": "正式覆核完成",
}
REVIEW_REASONS = {
    "none": "無", "input_limit": "輸入容量超限",
    "invalid_reference": "來源引用編號無效",
    "invalid_evidence": "證據內容不合規",
    "call_limit": "超出呼叫次數預算",
    "time_budget": "覆核耗時預算用盡",
    "llm_error": "模型呼叫失敗",
    "invalid_response": "模型覆核格式／引用不合規",
    "excessive_rejection": "擬排除比例過高，已取消全部排除",
    "high_rejection_rate": "排除比例超過預警門檻",
}


def safe_review(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != REVIEW_SCHEMA:
        return {}
    mode, status, reason = raw.get("mode"), raw.get("status"), raw.get("reason")
    if (mode not in REVIEW_MODES or status not in REVIEW_STATUSES
            or reason not in REVIEW_REASONS or type(raw.get("anomaly")) is not bool):
        return {}
    nums = {}
    keys = ("before", "after", "proposed_removed", "removed", "calls",
            "batches", "input_chars", "elapsed_ms", "batch_items_limit",
            "batch_char_limit")
    for name in keys:
        value = raw.get(name)
        if type(value) is not int or not 0 <= value <= 1_000_000_000:
            return {}
        nums[name] = value
    if (nums["after"] > nums["before"]
            or nums["removed"] != nums["before"] - nums["after"]
            or nums["proposed_removed"] > nums["before"]
            or nums["calls"] > 4 or nums["batches"] > 4 and nums["calls"] > 0
            or nums["batch_items_limit"] > 125 or nums["batch_char_limit"] > 24000
            or nums["input_chars"] > 96000
            or (status != "applied" and nums["removed"] != 0)
            or (status == "disabled" and mode != "off")
            or (status == "shadow" and mode != "shadow")):
        return {}
    return {
        "schema": REVIEW_SCHEMA, "mode": mode, "status": status, "reason": reason,
        "anomaly": raw["anomaly"], **nums,
    }


def review_rows(raw: Any) -> list[tuple[str, str]]:
    r = safe_review(raw)
    if not r:
        return []
    rows = [
        ("LLM 關聯性覆核模式", REVIEW_MODES[r["mode"]]),
        ("LLM 覆核狀態", REVIEW_STATUSES[r["status"]]),
        ("LLM 覆核前後", f"{r['before']} → {r['after']} 段；"
                         f"擬排除 {r['proposed_removed']} 段；實際排除 {r['removed']} 段"),
        ("LLM 覆核成本", f"{r['calls']} 次呼叫／預定 {r['batches']} 批；"
                         f"輸入約 {r['input_chars']} 字元（非 Token）；"
                         f"耗時 {r['elapsed_ms']} ms"),
        ("LLM 覆核異常", (REVIEW_REASONS[r["reason"]] if r["anomaly"]
                         else "未發現（僅代表規則檢查，不保證語意判斷正確）")),
    ]
    if r["status"] == "fallback":
        rows.append(("LLM 覆核降級處置", "原證據全部保留，不採用未完成或異常模型判斷"))
    return rows


NUMERIC = ("incoming", "strong", "weak", "picked", "compressed", "llm_input",
           "incoming_identified_sources", "picked_identified_sources",
           "llm_input_identified_sources", "max_for_llm", "prompt_chars",
           "truncated_notes", "truncated_titles")


def safe_evidence_usage(raw: Any) -> dict[str, Any]:
    """Reject malformed or content-bearing values; emit known counters only."""
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return {}
    mode = raw.get("selection_mode")
    if mode not in MODES or type(raw.get("llm_skipped_incomplete")) is not bool:
        return {}
    nums = {}
    for name in NUMERIC:
        value = raw.get(name)
        if type(value) is not int or not 0 <= value <= 1_000_000_000:
            return {}
        nums[name] = value
    if (nums["strong"] + nums["weak"] != nums["incoming"]
        or not nums["llm_input"] <= nums["compressed"] <= nums["picked"] <= nums["incoming"]
        or nums["picked"] > nums["max_for_llm"]
        or nums["incoming_identified_sources"] > nums["incoming"]
        or nums["picked_identified_sources"] > nums["picked"]
        or nums["llm_input_identified_sources"] > nums["llm_input"]):
        return {}
    clean = {"schema": SCHEMA, "selection_mode": mode,
             "llm_skipped_incomplete": raw["llm_skipped_incomplete"], **nums}
    review = safe_review(raw.get("review"))
    if review:
        clean["review"] = review
    return clean


def evidence_usage_rows(raw: Any) -> list[tuple[str, str]]:
    """Identical label/value lines for DOCX and Markdown."""
    usage = safe_evidence_usage(raw)
    if not usage:
        return []
    u = usage
    n = u["incoming_identified_sources"]
    kept = u["llm_input_identified_sources"]
    coverage = (f"{kept / n * 100:.1f}%（僅已識別來源）" if n
                else "無法計算（無已識別來源）")
    lines = [
        ("Evidence 選取模式", MODES[u["selection_mode"]]),
        ("Data Agent 傳入", f"{u['incoming']} 段／已識別來源 {n} 篇"),
        ("報告選取後", f"{u['picked']} 段／已識別來源 {u['picked_identified_sources']} 篇"),
        ("去重／壓縮後", f"{u['compressed']} 段"),
        ("報告 LLM 實際輸入", f"{u['llm_input']} 段／已識別來源 {kept} 篇"),
        ("已識別來源保留率", coverage),
        ("階段減少數",
         f"選取未納入 {u['incoming']-u['picked']} 段；壓縮減少 {u['picked']-u['compressed']} 段；欄位選擇減少 {u['compressed']-u['llm_input']} 段"),
        ("LLM Evidence 合計上限", f"{u['max_for_llm']} 段（非單篇上限）"),
        ("Prompt 長度", f"{u['prompt_chars']} 字元（非 Token 數）"),
        ("計數限制", "僅統計已取得、具有文件 ID 的來源；不代表議題覆蓋或檢索完整性"),
    ]
    lines.extend(review_rows(u.get("review")))
    if u["llm_skipped_incomplete"]:
        lines.append(("報告 LLM", "未執行（日期檢索不完整且無有效證據）"))
    return lines
