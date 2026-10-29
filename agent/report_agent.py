#agent/report_agent.py
from typing import Any, Dict, List, Optional
import json
import time
import os
from .data_agent import run_data_agent
#from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById
#from .tools_stats import AggregateMonthQuarter
from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝
from agent.utils.citations import build_citations_from_ev
from agent.utils.citations import compress_evidence
from agent.utils.citations import build_refno_uuid_map
from agent.utils.evidence_pack import pack_ev_for_llm
from agent.utils.evidence_pack import filter_ev_fields
from agent.utils.evidence_pack import guess_report_need_fields
from agent.utils.profiler import log_duration, log_total
from agent.utils.markdown_tables import sanitize_markdown_tables, replace_table_cell_br
from agent.refiners.query_refiner import refine_question_for_data_agent
#from agent.config.query_refiner_settings import load_report_refiner_config

from .report_config import REPORT_LLM_TIMEOUT, REPORT_MODEL_ID
from .report_prompt import REPORT_SYSTEM_PROMPT
from .report_stats import compress_stats


class ReportAgent:
    """
    run() 回傳 dict（含 citations），
    run_text() 回傳單純 answer。
    """
    def run(self, query: str) -> Dict[str, Any]:
        return ask_with_report(query)

    def run_text(self, query: str) -> str:
        result = ask_with_report(query)
        return result.get("answer", "").strip() or "[系統沒有產生任何文字答案]"
    
def ask_with_report(
    question: str,
    trace: Optional[Dict[str, Any]] = None,
    index_hint: str | None = None,
    
) -> Dict[str, Any]:
    if trace is None:
        trace = {}
    t_total_start = time.perf_counter()
    #print("question in ask_with_report",question)
    original_question = (question or "").strip()
    #print("original_question in ask_with_report",original_question)
    # ✅ 先精煉，再丟給 data_agent（只影響資料準備，不影響前端顯示的「使用者提問」）
    refined_question = refine_question_for_data_agent(
        original_question,
        mode="report",
        trace=trace,
        index_hint=index_hint, # ★ 新增
    )
    
    with log_duration("[report] run_data_agent", extra={"mode": "report"}):
        #payload = run_data_agent(refined_question, mode="report", trace=trace)
        payload = run_data_agent(
            refined_question,
            mode="report",
            trace=trace,
            question_raw=original_question,
            refined_question=refined_question,
            index_hint=index_hint,   # ✅ 補上
            route=trace.get("route")  # 或你當下的 route 變數
        )
        
    # ✅ 對外仍保留原問句（你原本就強調「使用者提問一定要存在」）
    payload["question"] = original_question or "[未提供使用者提問]"
    payload["question_raw"] = original_question or "[未提供使用者提問]"
    
    # ✅ 把精煉結果也留著（debug/稽核很有用）
    qm = payload.get("query_meta") or {}
    if isinstance(qm, dict):
        qm["refined_question"] = refined_question
        payload["query_meta"] = qm

    # 你可以用環境變數控管給 LLM 的最大片段數
    MAX_EV_FOR_LLM = int(os.getenv("REPORT_MAX_EVIDENCE_SNIPS", "120"))

    # 新增：前端回傳上限
    MAX_EV_FOR_FRONTEND_CFG = int(os.getenv("REPORT_MAX_EVIDENCE_SNIPS_FRONTEND", "150"))

    # 保底：前端至少 >= LLM（避免使用者覺得「前端比報告引用更少」）
    MAX_EV_FOR_FRONTEND = max(MAX_EV_FOR_FRONTEND_CFG, MAX_EV_FOR_LLM)
    
    # === 強/弱證據分流（強優先給報告 LLM）===
    ev_all = payload.get("evidence_snippets") or []
    ev_strong = [e for e in ev_all if not e.get("weak_evidence")]
    ev_weak   = [e for e in ev_all if e.get("weak_evidence")]
    
    # 強證據優先，不夠再補弱證據
    picked_for_llm = ev_strong[:MAX_EV_FOR_LLM]
    if len(picked_for_llm) < MAX_EV_FOR_LLM:
        need = MAX_EV_FOR_LLM - len(picked_for_llm)
        picked_for_llm += ev_weak[:need]
    
    # （可選）讓 payload 留個統計，方便 debug / 前端顯示
    payload["evidence_meta"] = {
        "total": len(ev_all),
        "strong": len(ev_strong),
        "weak": len(ev_weak),
        
        # LLM 相關
        "max_for_llm": MAX_EV_FOR_LLM,
        "picked_for_llm": len(picked_for_llm),
        
        # 前端相關（配置值 vs 實際生效值）
        "max_for_frontend_cfg": MAX_EV_FOR_FRONTEND_CFG,
        "max_for_frontend": MAX_EV_FOR_FRONTEND,
    
    }
    print("[report] evidence_meta =", payload["evidence_meta"])

    # === 精簡版（給報告 LLM 用） ===
    compressed_for_llm = {
        # 給報告 LLM：用精煉問句（避免字數/格式碎念干擾）
        "q": refined_question or payload.get("question"),
    
        # 若你希望報告內仍能提到「原問句」或做稽核：保留一份
        "q0": payload.get("question"),
        "t": [
            payload.get("time_range", {}).get("date_from"),
            payload.get("time_range", {}).get("date_to"),
        ],
        "agg": compress_stats(payload.get("stats") or {}),
        #"ev": compress_evidence(payload.get("evidence_snippets") or []),
        "ev": compress_evidence(picked_for_llm, max_samples=MAX_EV_FOR_LLM),
    }



    ev_compact = compressed_for_llm["ev"] or []
    payload["ev"] = ev_compact

    # === (止血) 單片 note 字元上限：避免 token 爆掉 ===
    NOTE_CHAR_LIMIT = int(os.getenv("REPORT_EV_NOTE_CHAR_LIMIT", "0"))  # 0=不限制
    TITLE_CHAR_LIMIT = int(os.getenv("REPORT_EV_TITLE_CHAR_LIMIT", "0"))  # 0=不限制（可選）

    truncated_notes = 0
    truncated_titles = 0
    note_truncated_chars_total = 0
    title_truncated_chars_total = 0

    if NOTE_CHAR_LIMIT > 0:
        for e in ev_compact:
            note = e.get("note")
            if isinstance(note, str) and len(note) > NOTE_CHAR_LIMIT:
                note_truncated_chars_total += (len(note) - NOTE_CHAR_LIMIT)
                e["note"] = note[:NOTE_CHAR_LIMIT] + "…"
                truncated_notes += 1

    # （可選）標題也可能很長，通常不太會，但加了更保險
    if TITLE_CHAR_LIMIT > 0:
        for e in ev_compact:
            title = e.get("title")
            if isinstance(title, str) and len(title) > TITLE_CHAR_LIMIT:
                title_truncated_chars_total += (len(title) - TITLE_CHAR_LIMIT)
                e["title"] = title[:TITLE_CHAR_LIMIT] + "…"
                truncated_titles += 1

    # === (可選) 整體 note 總字元預算：再加一道硬上限 ===
    NOTE_TOTAL_BUDGET = int(os.getenv("REPORT_EV_NOTE_TOTAL_BUDGET", "0"))  # 0=不限制
    if NOTE_TOTAL_BUDGET > 0:
        total = 0
        for e in ev_compact:
            note = e.get("note")
            if not isinstance(note, str):
                continue
            if total >= NOTE_TOTAL_BUDGET:
                # 超過預算後，直接把後面的 note 清空或改成極短提示（更省）
                e["note"] = "…"
                continue

            remain = NOTE_TOTAL_BUDGET - total
            if len(note) > remain:
                e["note"] = note[:remain] + "…"
                total = NOTE_TOTAL_BUDGET
            else:
                total += len(note)
                
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["note_char_limit"] = NOTE_CHAR_LIMIT
        em["title_char_limit"] = TITLE_CHAR_LIMIT
        em["truncated_notes"] = truncated_notes
        em["truncated_titles"] = truncated_titles
        em["note_truncated_chars_total"] = note_truncated_chars_total
        em["title_truncated_chars_total"] = title_truncated_chars_total
        em["note_total_budget"] = NOTE_TOTAL_BUDGET
        
    try:
        packed = pack_ev_for_llm(
            ev_compact,
            refined_question or payload.get("question") or "",
            mode=os.getenv("REPORT_EV_FIELD_SELECTOR_MODE", "rules"),
            call_llm_fn=call_llm,
            llm_model=os.getenv("REPORT_FIELD_SELECTOR_MODEL_ID") or REPORT_MODEL_ID,
            llm_timeout=float(os.getenv("REPORT_FIELD_SELECTOR_TIMEOUT", "60")),
            llm_max_fields=int(os.getenv("REPORT_FIELD_SELECTOR_MAX_FIELDS", "10")),
        )
    except Exception as ex:
        # 保底：任何錯誤都不要影響主流程
        packed = {
            "ev_slim": filter_ev_fields(ev_compact, guess_report_need_fields(refined_question or "")),
            "meta": {
                "mode": "rules", "llm_used": False, "llm_attempted": False,
                "fallback_used": True, "fallback_strategy": "rules",
                "llm_error": "selector_error",
                "allow_fields": sorted(guess_report_need_fields(refined_question or "")),
                "fields_count": len(guess_report_need_fields(refined_question or "")),
            }
        }
    compressed_for_llm["ev"] = packed["ev_slim"]

    selector_mode = packed["meta"].get("mode")
    if (packed["meta"].get("llm_used") or packed["meta"].get("llm_error")
            or packed["meta"].get("fallback_used")):
        selector_model = os.getenv("REPORT_FIELD_SELECTOR_MODEL_ID") or REPORT_MODEL_ID
        degraded = bool(packed["meta"].get("fallback_used"))
        trace.setdefault("llm", {}).setdefault("field_selector", []).append({
            "model_id": selector_model,
            "status": "fallback" if degraded else "success",
            "error": packed["meta"].get("llm_error"),
            "detail": f"mode={selector_mode}; fallback=rules" if degraded else f"mode={selector_mode}",
        })
    
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["llm_ev_fields"] = packed["meta"].get("allow_fields")
        em["llm_ev_fields_count"] = packed["meta"].get("fields_count")
        em["llm_ev_field_selector"] = {
            "mode": packed["meta"].get("mode"),
            "llm_used": packed["meta"].get("llm_used"),
            "llm_attempted": packed["meta"].get("llm_attempted"),
            "llm_error": packed["meta"].get("llm_error"),
            "fallback_used": packed["meta"].get("fallback_used", False),
            "fallback_strategy": packed["meta"].get("fallback_strategy"),
        }
        em["llm_ev_returned"] = len(compressed_for_llm["ev"])
        
    # === related_articles：建議只列出 LLM 有用到的這些 doc ===
    ev_full = payload.get("evidence_snippets") or []
    
    # 取用於對齊的 doc_id（與 ev_compact 的 id 同概念）
    def _doc_id_from_full_snip(s: Dict[str, Any]) -> str:
        return str(s.get("uuid") or s.get("source_id") or "")
    
    used_ids = {str(e.get("id")) for e in ev_compact if e.get("id")}
    
    related_map: Dict[str, Dict[str, Any]] = {}
    for s in ev_full:
        doc_id = _doc_id_from_full_snip(s)
        if not doc_id:
            continue
        if used_ids and doc_id not in used_ids:
            continue
        if doc_id in related_map:
            continue
    
        related_map[doc_id] = {
            "uuid": s.get("uuid"),
            "source_id": s.get("source_id"),
            "article_title": s.get("article_title"),
            "article_date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
        }
    
    payload["related_articles"] = list(related_map.values())

    # === 給 LLM 的 JSON ===
    user_prompt = json.dumps(
        compressed_for_llm,
        ensure_ascii=False,
        separators=(",", ":")
    )
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["llm_user_prompt_chars"] = len(user_prompt)  # ★ 可選但很實用
    #ev_for_llm = ev_compact
    ev_for_llm = compressed_for_llm["ev"]  # ★ 改成真的送進去那份
    
    print(f"MAX_EV_FOR_LLM:{MAX_EV_FOR_LLM}")
    print(f"MAX_EV_FOR_FRONTEND_CFG:{MAX_EV_FOR_FRONTEND_CFG}")
    print("=== DEBUG: EV (for LLM) ===")
    for e in ev_for_llm:
        print({
            "ref_no": e.get("ref_no"),
            "id": e.get("id"),
            "d": e.get("d"),
            "title": e.get("title"),
            "note_preview": (e.get("note") or "")[:100].replace("\n", " "),
            "keys": list(e.keys()),  # 這行對診斷欄位精簡很有用
        })
    t0 = time.perf_counter()
    with log_duration("[report] call_llm(report)",
        extra={"model_id": REPORT_MODEL_ID, "timeout_sec": REPORT_LLM_TIMEOUT},
    ):
        report_text = call_llm(
            user_prompt,
            system_prompt=REPORT_SYSTEM_PROMPT,
            extra_params={"options": {}},
            # 可用 REPORT_LLM_TIMEOUT（或舊名 REPORT_TIMEOUT）延長大型報告生成等待秒數
            timeout=REPORT_LLM_TIMEOUT,
            model=REPORT_MODEL_ID,
        )
    t1 = time.perf_counter()
    
    # ★ 修復 LLM 產出的所有 Markdown 表格（不限欄數）
    #print(f"DEBUG: report_text before Sanitized Markdown Row: {report_text}")
    if "<br>\n" in report_text or "<br />\n" in report_text or "<br/>\n" in report_text:
        print("FOUND br+newline inside output table!")
    if isinstance(report_text, str) and report_text.strip():
        report_text = sanitize_markdown_tables(report_text)
        # ★ OpenWebUI 容易對 <br> 的表格渲染出問題：把表格 cell 內的 <br> 改成分隔符
        report_text = replace_table_cell_br(report_text, sep="；")  # 你也可改成 " / "
    #print(f"DEBUG: report_text after Sanitized Markdown Row: {report_text}")
    # ★ 把這次報告 LLM 寫到 trace["llm"]["report"]
    llm_root = trace.setdefault("llm", {})
    report_logs: list[Dict[str, Any]] = llm_root.setdefault("report", [])
    #print("REPORT_SYSTEM_PROMPT",REPORT_SYSTEM_PROMPT)
    report_logs.append({
        "system": "REPORT_SYSTEM_PROMPT",
        "user": user_prompt,
        "answer_preview": (report_text[:200] if isinstance(report_text, str) else str(report_text)[:200]),
        "elapsed_sec": round(t1 - t0, 3),
        "model_id": REPORT_MODEL_ID,
    })
    
    # === evidence_snippets 仍可保留給其他用途（例如前端展開全文），但不再用來建 citations ===
    ev_for_frontend = payload.get("evidence_snippets") or []
    if len(ev_for_frontend) > MAX_EV_FOR_FRONTEND:
        ev_for_frontend = ev_for_frontend[:MAX_EV_FOR_FRONTEND]
        payload["evidence_snippets"] = ev_for_frontend

    # ✅ 寫入實際前端回傳數量
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["frontend_returned"] = len(ev_for_frontend)
    
    # ★ citations：直接用 ev_compact
    citations = build_citations_from_ev(ev_compact)

    reasoning = (
        "本回答根據 es_search_news 的查詢結果與 aggregate_month_quarter 所提供的統計，"
        "並綜整 evidence_snippets 及相關文章所做的資料驅動分析。"
    )

    # ★ used_uuids：也從 ev_compact 算，確保跟 LLM 實際用的一致
    used_uuids: List[str] = []
    for e in ev_compact:
        doc_id = e.get("id")
        if doc_id:
            doc_id = str(doc_id)
            if doc_id not in used_uuids:
                used_uuids.append(doc_id)
    refno_uuid_map = build_refno_uuid_map(ev_compact)
    #print("report_text",report_text)
    result: Dict[str, Any] = {
        "question": original_question or "[未提供使用者提問]",   # ✅ 給匯出用（最重要）
        "q": refined_question or (original_question or ""),      # ✅ 可選：給 debug 或一致性
        "q0": original_question or "",                           # ✅ 可選：保留原問句
        "answer": report_text,
        "citations": citations,
        "reasoning": reasoning,
        "used_uuids": used_uuids,
        "refno_uuid_map": refno_uuid_map,
    }

    # ★ 把資料整備代理人的 log 掛回給前端用
    data_agent = trace.get("data_agent")
    if data_agent:
        result["data_agent"] = data_agent

    # ★ 總耗時 log（報告管線整體）
    log_total(
        "[report] ask_with_report[TOTAL]",
        t_total_start,
        extra={
            "ev_count": len(ev_compact),
            "docs": compressed_for_llm.get("agg", {}).get("docs"),
        },
    )
    
    return result
