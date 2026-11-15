"""Only numeric Report Evidence statistics shared by Word and OpenWebUI."""
from __future__ import annotations
from typing import Any

SCHEMA = "sraf_report_evidence_usage_v1"
MODES = {"strong_first": "強證據優先（原模式）", "source_diverse": "來源多樣性（強證據優先）"}
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
    return {"schema": SCHEMA, "selection_mode": mode,
            "llm_skipped_incomplete": raw["llm_skipped_incomplete"], **nums}


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
    if u["llm_skipped_incomplete"]:
        lines.append(("報告 LLM", "未執行（日期檢索不完整且無有效證據）"))
    return lines
