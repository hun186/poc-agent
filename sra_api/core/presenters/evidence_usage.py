"""Only numeric Report Evidence statistics shared by Word and OpenWebUI."""
from __future__ import annotations
from typing import Any

from .nround_progress import nround_progress_rows, safe_nround_progress

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


TOPIC_SCHEMA = "sraf_topic_adaptive_report_v1"
TOPIC_SCOPE = "data_agent_tool_slices_not_global_recall"
TOPIC_MODES = {"off", "shadow", "on"}
TOPIC_KEYS = ("slices", "strict", "proposed", "selected",
              "no_anchor", "not_low", "attempted", "uninspected")


def safe_topic_adaptive(raw: Any) -> dict[str, Any]:
    """Strictly count-only audit; never pass model-/question-supplied strings."""
    if not isinstance(raw, dict) or raw.get("schema") != TOPIC_SCHEMA:
        return {}
    if raw.get("scope") != TOPIC_SCOPE or raw.get("mode") not in TOPIC_MODES:
        return {}
    if type(raw.get("truncated")) is not bool:
        return {}
    vals = {}
    for key in TOPIC_KEYS:
        value = raw.get(key)
        if type(value) is not int or not 0 <= value <= 1_000_000:
            return {}
        vals[key] = value
    if (vals["slices"] > 32 or vals["attempted"] > vals["slices"]
            or vals["no_anchor"] > vals["slices"]
            or vals["not_low"] > vals["slices"]
            or vals["selected"] > vals["proposed"]
            or vals["selected"] > 2 * vals["attempted"]
            or (raw["mode"] != "on" and vals["selected"] != 0)
            or (raw["mode"] == "off" and vals["slices"] != 0)):
        return {}
    prose = raw.get("prose_shadow_slices", 0)
    if (type(prose) is not int or not 0 <= prose <= vals["attempted"]
            or (prose and raw["mode"] != "shadow")):
        return {}
    return {"schema": TOPIC_SCHEMA, "scope": TOPIC_SCOPE,
            "mode": raw["mode"], "truncated": raw["truncated"],
            "prose_shadow_slices": prose, **vals}


def topic_adaptive_rows(raw: Any) -> list[tuple[str, str]]:
    r = safe_topic_adaptive(raw)
    if not r:
        return []
    if r["mode"] == "off":
        status = "未啟用：沿用原本嚴格篩選，沒有計算 3→2 候選"
    elif r["mode"] == "shadow":
        status = "觀察模式：有計算較寬鬆候選，但正式報告仍使用原本篩選結果"
    else:
        status = "受控啟用：僅有符合必要主題及日期限制的弱證據才可能加入"
    if r["slices"] == 0 and r["mode"] != "off":
        status += "；本次未取得可用的工具階段紀錄"
    rows = [
        ("主題檢索智慧放寬", status),
        ("嚴格篩選與預估增補",
         f"工具檢查批次 {r['slices']} 次；原規則合格計數合計 {r['strict']} 段；"
         f"2 組命中且通過必要主題限制的候選 {r['proposed']} 段；"
         f"在初步檢索階段實際加入 {r['selected']} 段"),
    ]
    if r["mode"] != "off":
        rows.append((
            "未放寬的原因",
            f"因原問題未明確指定必要主題：{r['no_anchor']} 批；"
            f"原本證據並非低量：{r['not_low']} 批；"
            f"實際進行候選評估：{r['attempted']} 批",
        ))
    if r["prose_shadow_slices"]:
        rows.append((
            "自然語句主題推估（僅觀察）",
            f"有 {r['prose_shadow_slices']} 個工具批次從原始問句的開頭"
            "推測可能的必要主題，僅試算較寬鬆候選；這不是已驗證的實體辨識，"
            "也不會讓這些候選自動加入正式報告",
        ))
    if r["truncated"]:
        rows.append(("檢索歷程不完整",
                     "此次工具執行超過 32 個批次，以下計數僅涵蓋前 32 批；"
                     "後續仍可能加入弱證據，不能把此統計視為全程總數"))
    if r["uninspected"]:
        rows.append(("檢索抽樣範圍提醒",
                     f"仍有 {r['uninspected']} 筆解析器候選未被本層檢查，"
                     "不能宣稱已找齊所有資料"))
    rows.append(("檢索歷程計數說明",
                 "以上為 Data Agent 工具處理批次合計，補抓或分頁可能重複計數；"
                 "不是最終報告實際引用數，也不代表資料相關性或召回率已通過人工驗證"))
    return rows


CITATION_STATUSES = {
    "labels_match": "編號均可對應（不代表內容正確）",
    "unmapped": "發現無法對應的引用編號",
    "no_labels": "未見標準來源編號（不能確認有無引用）",
    "invalid_contract": "檢查資料不合規，未完成核對",
    "limit_exceeded": "檢查容量達上限，未完成核對",
}
INFORMATION_STATUSES = {
    "limited_text": "部分片段過短，須核對全文",
    "measured_only": "已計數，未進行語意正確性判斷",
    "no_evidence": "本層無 Evidence（另由零證據規則處理）",
    "not_assessed": "資訊量無法安全計算",
}


def safe_citation_label_audit(raw: Any) -> dict[str, Any]:
    if type(raw) is not dict or raw.get("schema") != "sraf_report_citation_labels_v1":
        return {}
    if raw.get("status") not in CITATION_STATUSES:
        return {}
    keys = ("labels_seen", "unique_labels", "unmapped_labels", "allowed_reference_count")
    values = {}
    for name in keys:
        val = raw.get(name)
        if type(val) is not int or not 0 <= val <= 10000:
            return {}
        values[name] = val
    if (values["allowed_reference_count"] > 500
            or values["unmapped_labels"] > values["unique_labels"]
            or values["unique_labels"] > values["labels_seen"]
            or (raw["status"] == "labels_match" and
                (values["labels_seen"] == 0 or values["unmapped_labels"] != 0))
            or (raw["status"] == "unmapped" and values["unmapped_labels"] == 0)
            or (raw["status"] == "no_labels" and values["labels_seen"] != 0)):
        return {}
    return {"schema": "sraf_report_citation_labels_v1", "status": raw["status"], **values}


def safe_evidence_information(raw: Any) -> dict[str, Any]:
    if type(raw) is not dict or raw.get("schema") != "sraf_report_evidence_information_v1":
        return {}
    if raw.get("status") not in INFORMATION_STATUSES:
        return {}
    limits = {"rows": 500, "total_visible_chars": 2_000_000,
              "short_notes": 500, "date_only_notes": 500}
    result = {}
    for key, cap in limits.items():
        val = raw.get(key)
        if type(val) is not int or not 0 <= val <= cap:
            return {}
        result[key] = val
    if (result["short_notes"] > result["rows"]
            or result["date_only_notes"] > result["rows"]
            or (raw["status"] in ("no_evidence", "not_assessed") and result["rows"] != 0)):
        return {}
    return {"schema": "sraf_report_evidence_information_v1", "status": raw["status"], **result}


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
    skip_empty = raw.get("llm_skipped_no_evidence", False)
    if type(skip_empty) is not bool:
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
        or nums["llm_input_identified_sources"] > nums["llm_input"]
        or (skip_empty and (nums["incoming"] != 0 or nums["llm_input"] != 0))):
        return {}
    clean = {"schema": SCHEMA, "selection_mode": mode,
             "llm_skipped_incomplete": raw["llm_skipped_incomplete"],
             "llm_skipped_no_evidence": skip_empty, **nums}
    review = safe_review(raw.get("review"))
    if review:
        clean["review"] = review
    topic = safe_topic_adaptive(raw.get("topic_adaptive"))
    if topic:
        clean["topic_adaptive"] = topic
    # Future N-round Report Job may attach count-only coordinator progress.
    # Never carry private question, ES identities or evidence from raw input.
    nround = safe_nround_progress(raw.get("nround_progress"))
    if nround:
        clean["nround_progress"] = nround
    citation = safe_citation_label_audit(raw.get("citation_labels"))
    if citation:
        clean["citation_labels"] = citation
    information = safe_evidence_information(raw.get("evidence_information"))
    if information:
        clean["evidence_information"] = information
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
    lines.extend(topic_adaptive_rows(u.get("topic_adaptive")))
    lines.extend(review_rows(u.get("review")))
    lines.extend(nround_progress_rows(u.get("nround_progress")))
    citation = u.get("citation_labels")
    if citation:
        lines.append(("來源編號一致性", CITATION_STATUSES[citation["status"]]))
        lines.append(("來源編號檢查範圍",
                      f"本層找到 {citation['labels_seen']} 個標記，"
                      f"其中未能對應 {citation['unmapped_labels']} 個不同編號；"
                      "僅核對編號，不保證引用內容有事實依據"))
    information = u.get("evidence_information")
    if information:
        lines.append(("Evidence 資訊量提醒", INFORMATION_STATUSES[information["status"]]))
        lines.append(("Evidence 資訊量計數",
                      f"傳給模型 {information['rows']} 段；非空白字元約 "
                      f"{information['total_visible_chars']}；"
                      f"短片段 {information['short_notes']} 段；"
                      f"日期型片段 {information['date_only_notes']} 段；"
                      "這是機械計數，並非品質、完整性或可信度評分"))
    if u["llm_skipped_incomplete"]:
        lines.append(("報告 LLM", "未執行（日期檢索不完整且無有效證據）"))
    elif u["llm_skipped_no_evidence"]:
        lines.append(("報告 LLM", "未執行（缺少可核對的有效 Evidence，並非已證實沒有事件）"))
    return lines
