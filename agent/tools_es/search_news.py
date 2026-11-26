# agent/tools_es/search_news.py
from __future__ import annotations

import time
import os
import re
from typing import Any, Dict, List, Optional

from elasticsearch import BadRequestError
from smolagents import Tool

from agent.es.es_client import safe_search as _safe_es_search
from agent.es.arc_frequency_shadow import native_frequency_enabled
from agent.es.arc_bilingual_shadow import observe_bilingual_proposal
from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
from agent.es.evidence_core.arc_relax_shadow import StrictSliceCounts, observe_low_volume, log_low_volume
from agent.es.arc_request_budget import current_arc_budget
from agent.es.arc_strategy_shadow import observe_strategy, strategy_enabled
from agent.es.ordinary_scope_receipt import current_ordinary_scope_capture
from agent.es.query_terms import compute_effective_terms
from agent.es.evidence import build_hits_and_evidence
from agent.es.query_body import build_main_query_body, build_fallback_query_body
from .date_refill import refill_date_filtered_evidence
from .question_scope import get_original_report_question
from agent.utils.profiler import log_duration, log_total

from .common import (
    dbg,
    normalize_size,
    resolve_index,
    flatten_syn_terms,
    build_query_meta,
    propagate_requirement_acceptance,
)


class ESSearchNews(Tool):
    name = "es_search_news"
    description = "BM25 + nested 日期過濾；回傳證據段落、uuid、subject、分數等。"
    inputs = {
        "query": {
            "type": "string",
            "description": "使用者查詢關鍵字（必填）",
            "nullable": True
        },
        "must_high_value": {
            "type": "boolean",
            "description": "是否只回傳 AI 判定高價值文件（預設 False：改以加權提升）",
            "default": False,
            "nullable": True
        },
        "must_selected": {
            "type": "boolean",
            "description": "是否只回傳人審選取（selectedMessage=true）的文件（預設 False）",
            "default": False,
            "nullable": True
        },
        "size": {
            "type": "integer",
            "description": "返回筆數上限（1–10000；預設 10000）",
            "default": 10000, "minimum": 1, "maximum": 10000, "nullable": True
        },
        "date_from": {
            "type": "string",
            "description": "ISO 起始日期（YYYY-MM-DD）；nested 檢索 Event 與 Event_Timeline 時間區間",
            "nullable": True
        },
        "date_to": {
            "type": "string",
            "description": "ISO 結束日期（YYYY-MM-DD）；nested 檢索 Event 與 Event_Timeline 時間區間",
            "nullable": True
        },
        "selected_boost": {
            "type": "number",
            "description": "人審文件加權（function_score weight；預設 6.0）",
            "default": 6.0,
            "nullable": True
        },
        "high_value_boost": {
            "type": "number",
            "description": "AI 高價值文件加權（function_score weight；預設 2.5）",
            "default": 2.5,
            "nullable": True
        },
        "recency_boost": {
            "type": "boolean",
            "description": "是否啟用「時間衰減」新鮮度加分（預設 False）",
            "default": False,
            "nullable": True
        },
        "recency_field": {
            "type": "string",
            "description": "新鮮度欄位（預設 importDT，可改 multidim_event_json.update_time_ai）",
            "default": "importDT",
            "nullable": True
        },
        "recency_scale": {
            "type": "string",
            "description": "高斯衰減尺度（如 '30d'、'90d'；預設 '30d'）",
            "default": "30d",
            "nullable": True
        },
        # === 新增：給 LLM 路由用的 index hint ===
        "index_hint": {
            "type": "string",
            "description": "由 LLM 分流傳入的索引提示字串；若未提供則使用環境變數 ES_INDEX",
            "nullable": True
        }
    }

    output_type = "any"

    @propagate_requirement_acceptance
    def forward(
        self,
        query: Optional[str] = None,
        must_high_value: Optional[bool] = False,
        must_selected: Optional[bool] = False,
        size: Optional[int] = 10000,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        selected_boost: Optional[float] = 6.0,
        high_value_boost: Optional[float] = 2.5,
        recency_boost: Optional[bool] = False,
        recency_field: Optional[str] = "importDT",
        recency_scale: Optional[str] = "30d",
        index_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        t_start = time.perf_counter()
        size = normalize_size(size)

        if not query:
            return {"hits": [], "evidence_snippets": [], "error": "query is required"}

        raw_query = (query or "").strip()
        es_query = raw_query  # 目前等同 raw_query；未來你要加特殊語法也可改這裡
        index = resolve_index(index_hint)

        dbg("[es_search_news] search request accepted (content redacted)")

        # === T1: 抽詞 ===
        with log_duration("[es_search_news][T1] compute_effective_terms"):
            (
                core_terms,
                grouped_syns,
                is_manual_entity_query,
                manual_terms_in_q,
                effective_terms,
                term_groups,
            ) = compute_effective_terms(raw_query)

        syn_terms_flat: List[str] = flatten_syn_terms(grouped_syns)
        all_terms = list(effective_terms or [])

        # === T2: build query body ===
        with log_duration("[es_search_news][T2] build_main_query_body"):
            body = build_main_query_body(
                es_query,
                must_high_value,
                must_selected,
                size,
                date_from,
                date_to,
                selected_boost,
                high_value_boost,
                recency_boost,
                recency_field,
                recency_scale,
                with_date=True,
                effective_terms=effective_terms,
                core_terms=core_terms,
                syn_terms=syn_terms_flat,
                all_terms=all_terms,
                original_question=get_original_report_question(),
            )
        capture = current_ordinary_scope_capture()
        if capture is not None:
            capture.declare_search(
                index=index, date_from=date_from, date_to=date_to,
                core_terms=core_terms, body=body, manual=is_manual_entity_query,
                must_high_value=must_high_value, must_selected=must_selected,
                raw_query=es_query,
            )
        dbg("[es_search_news] ES query body prepared (content redacted)")

        native_rank_receipts = []
        # === T3: ES 查詢 ===
        try:
            with log_duration("[es_search_news][T3] _safe_es_search", extra={"size": size}):
                if native_frequency_enabled():
                    res = _safe_es_search(body, index=index, arc_frequency={
                        "groups": term_groups, "date_from": date_from,
                        "date_to": date_to,
                        "must_high_value": False if must_high_value is None else must_high_value,
                        "must_selected": False if must_selected is None else must_selected,
                        **({"receipt_sink": native_rank_receipts}
                           if (os.getenv("SRAF_ARC_RANK_NATIVE") == "shadow"
                               or os.getenv("SRAF_ARC_TIGHTEN") == "shadow") else {}),
                    })
                else:
                    res = _safe_es_search(body, index=index)
        except BadRequestError:
            print("[es_search_news] ES BadRequestError (details suppressed)")
            raise

        pressure = None
        if (os.getenv("SRAF_ARC_TIGHTEN") == "shadow"
                or os.getenv("SRAF_ARC_RELAX") == "shadow"
                or strategy_enabled()) and capture is None:
            from agent.external_capabilities import requirement_acceptance_active
            if not requirement_acceptance_active():
                pressure = CandidatePressure.from_primary(res)
        strategy_pressure = pressure if strategy_enabled() else None
        strategy_diagnostics = {}
        # Optional count-only observation; original query and groups remain authoritative.
        observe_bilingual_proposal(
            original_question=get_original_report_question(),
            groups=term_groups, manual=is_manual_entity_query,
        )
        hits = ((res.get("hits") or {}).get("hits") or []) if isinstance(res, dict) else []
        # Query-body years also constrain time: align Evidence-stage refill.
        allowed_years = (
            set(int(y) for y in re.findall(r"(?:19|20)\d{2}", es_query))
            if not (date_from or date_to) else None
        )
        date_scoped = bool(date_from or date_to or allowed_years)
        date_refill_meta: Optional[Dict[str, Any]] = None

        # A truly empty ES date query does not call the script-free fallback.
        if not hits:
            if (os.getenv("SRAF_ARC_RELAX") == "shadow"
                    and type(pressure) is CandidatePressure and current_arc_budget() is not None):
                try:
                    log_low_volume(observe_low_volume(
                        [], [], term_groups, counts=StrictSliceCounts(), pressure=pressure,
                        original_question=get_original_report_question(),
                        date_from=date_from, date_to=date_to, allowed_years=allowed_years,
                    ))
                except Exception:
                    log_low_volume({"schema": "sraf_arc_relax_shadow_v1", "status": "unavailable"})
            if date_scoped:
                if strategy_pressure is not None:
                    observe_strategy(pressure=strategy_pressure, diagnostics=strategy_diagnostics,
                                     final_count=0, strong_count=0, refill=None,
                                     original_question=get_original_report_question(),
                                     groups=term_groups, manual=is_manual_entity_query)
                query_meta = build_query_meta(
                    raw_query=raw_query,
                    es_query=es_query,
                    core_terms=core_terms or [],
                    syn_terms=syn_terms_flat,
                    effective_terms=list(effective_terms or []),
                    manual_terms_in_q=list(manual_terms_in_q or []),
                    is_manual_entity_query=bool(is_manual_entity_query),
                    term_groups=term_groups or [],
                    date_from=date_from,
                    date_to=date_to,
                )
                query_meta["note"] = "0_hits_with_date_filter"
                return {"hits": [], "evidence_snippets": [], "query_meta": query_meta}

            pressure = None  # fallback is not the primary query scope
            strategy_pressure = None
            dbg(">>>>>>>> [FALLBACK] using NON-SCRIPT query")
            body = build_fallback_query_body(es_query, must_high_value, must_selected, size)
            try:
                res = _safe_es_search(body, index=index)
            except BadRequestError:
                print("[es_search_news] ES BadRequestError (fallback; details suppressed)")
                raise
            hits = ((res.get("hits") or {}).get("hits") or []) if isinstance(res, dict) else []

        # === T4: 後處理：hits + evidence ===
        with log_duration("[es_search_news][T4] build_hits_and_evidence"):
            def _build_candidates(candidate_hits: List[Dict[str, Any]]):
                nonlocal pressure
                initial_pressure, pressure = pressure, None
                # Refill accumulates pages. Consume only at its first build;
                # never transfer a prior search's DF to a later tool/page.
                native_receipt = native_rank_receipts.pop() if native_rank_receipts else None
                return build_hits_and_evidence(
                    candidate_hits,
                    date_from=date_from,
                    date_to=date_to,
                    allowed_years=allowed_years,
                    include_source_hit_ordinal=date_scoped,
                    effective_terms=effective_terms,
                    term_groups=term_groups,
                    query_for_snippet=raw_query,
                    # Only an authenticated ReportAgent's bounded per-tool
                    # original provenance may supply an explicit subject.
                    # Direct ES tools, style calls or missing originals yield
                    # None; the LLM-rewritten raw_query is never substituted.
                    original_question=get_original_report_question(),
                    **({"native_rank_frequency": native_receipt} if native_receipt is not None else {}),
                    **({"arc_candidate_pressure": initial_pressure} if initial_pressure is not None else {}),
                    **({"arc_strategy_diagnostics": strategy_diagnostics}
                       if initial_pressure is not None and strategy_pressure is not None else {}),
                )

            if date_scoped:
                filtered_hits, evidence_snippets, syn_snippets, date_refill_meta = (
                    refill_date_filtered_evidence(
                        body=body,
                        first_response=res,
                        requested_size=size,
                        search_next=lambda next_body: _safe_es_search(next_body, index=index),
                        build_evidence=_build_candidates,
                    )
                )
            else:
                # Keep no-date queries as one request with their old fallback.
                filtered_hits, evidence_snippets, syn_snippets = _build_candidates(hits)

        strong_snippets = [ev for ev in evidence_snippets if not ev.get("weak_evidence")]
        weak_snippets = [ev for ev in evidence_snippets if ev.get("weak_evidence")]

        if strategy_pressure is not None:
            observe_strategy(pressure=strategy_pressure, diagnostics=strategy_diagnostics,
                             final_count=len(evidence_snippets), strong_count=len(strong_snippets),
                             refill=date_refill_meta, original_question=get_original_report_question(),
                             groups=term_groups, manual=is_manual_entity_query)

        # Log timing and counts, never the raw question, ES DSL, index or terms.
        log_total("[es_search_news][TOTAL]", t_start)

        print(
            f"[es_search_news] hits={len(filtered_hits)} "
            f"snippets_after_filter={len(evidence_snippets)} "
            f"effective_term_count={len(effective_terms or [])} "
            f"synonym_hit_snippets={syn_snippets}"
        )
        
        query_meta = build_query_meta(
            raw_query=raw_query,
            es_query=es_query,
            core_terms=core_terms or [],
            syn_terms=syn_terms_flat,
            effective_terms=list(effective_terms or []),
            manual_terms_in_q=list(manual_terms_in_q or []),
            is_manual_entity_query=bool(is_manual_entity_query),
            term_groups=term_groups or [],
            date_from=date_from,
            date_to=date_to,
        )

        if date_refill_meta is not None:
            query_meta["date_candidate_refill"] = date_refill_meta
            if date_refill_meta["incomplete_due_to_scan_limit"]:
                # Preserve the existing public result note for scan cap.
                query_meta["result_incomplete"] = True
                query_meta["note"] = "date_candidate_scan_limit_reached"
            elif date_refill_meta.get("incomplete_due_to_page_admission") is True:
                # A future request-wide budget may deny extra pages; never
                # imply this is exhaustive search or the existing scan cap.
                query_meta["result_incomplete"] = True
                query_meta["note"] = "additional_page_admission_denied"

        dbg(
            f"[es_search_news] hits={len(filtered_hits)}, "
            f"snippets={len(evidence_snippets)}, syn_hit_snippets={syn_snippets}"
        )

        return {
            "hits": filtered_hits,
            "evidence_snippets": evidence_snippets,
            "evidence_snippets_strong": strong_snippets,
            "evidence_snippets_weak": weak_snippets,
            "query_meta": query_meta,
        }
