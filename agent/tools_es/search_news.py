# agent/tools_es/search_news.py
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from elasticsearch import BadRequestError
from smolagents import Tool

from agent.es.es_client import safe_search as _safe_es_search
from agent.es.query_terms import compute_effective_terms
from agent.es.evidence import build_hits_and_evidence
from agent.es.query_body import build_main_query_body, build_fallback_query_body
from agent.utils.profiler import log_duration, log_total

from .common import (
    dbg,
    normalize_size,
    resolve_index,
    flatten_syn_terms,
    build_query_meta,
)


class ESSearchNews(Tool):
    name = "es_search_news"
    description = "BM25 + nested 日期過濾；回傳證據段落、uuid、subject、分數等。"
    '''
    inputs = {
        "query": {"type": "string", "description": "使用者查詢關鍵字（必填）", "nullable": True},
        "must_high_value": {"type": "boolean", "description": "是否只回傳 AI 判定高價值文件（預設 False：改以加權提升）", "default": False, "nullable": True},
        "must_selected": {"type": "boolean", "description": "是否只回傳人審選取（selectedMessage=true）的文件（預設 False）", "default": False, "nullable": True},
        "size": {"type": "integer", "description": "返回筆數上限（1–10000；預設 10000）", "default": 10000, "minimum": 1, "maximum": 10000, "nullable": True},
        "date_from": {"type": "string", "description": "ISO 起始日期（YYYY-MM-DD）；nested 過濾 Event_Timeline.date_iso", "nullable": True},
        "date_to": {"type": "string", "description": "ISO 結束日期（YYYY-MM-DD）；nested 過濾 Event_Timeline.date_iso", "nullable": True},
        "selected_boost": {"type": "number", "description": "人審文件加權（function_score weight；預設 6.0）", "default": 6.0, "nullable": True},
        "high_value_boost": {"type": "number", "description": "AI 高價值文件加權（function_score weight；預設 2.5）", "default": 2.5, "nullable": True},
        "recency_boost": {"type": "boolean", "description": "是否啟用「時間衰減」新鮮度加分（預設 False）", "default": False, "nullable": True},
        "recency_field": {"type": "string", "description": "新鮮度欄位（預設 importDT，可改 multidim_event_json.update_time_ai）", "default": "importDT", "nullable": True},
        "recency_scale": {"type": "string", "description": "高斯衰減尺度（如 '30d'、'90d'；預設 '30d'）", "default": "30d", "nullable": True},
        "index_hint": {"type": "string", "description": "由 LLM 分流傳入的索引提示字串；若未提供則使用環境變數 ES_INDEX", "nullable": True},
    }
    '''
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
            "description": "ISO 起始日期（YYYY-MM-DD）；nested 過濾 Event_Timeline.date_iso",
            "nullable": True
        },
        "date_to": {
            "type": "string",
            "description": "ISO 結束日期（YYYY-MM-DD）；nested 過濾 Event_Timeline.date_iso",
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

        dbg("[es_search_news] index =", index, "query =", raw_query)

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
            )
        print("[es_search_news] body =", json.dumps(body, ensure_ascii=False)[:4000])

        # === T3: ES 查詢 ===
        try:
            with log_duration("[es_search_news][T3] _safe_es_search", extra={"index": index, "size": size}):
                res = _safe_es_search(body, index=index)
                
                shards = (res or {}).get("_shards") if isinstance(res, dict) else None
                print("[es_search_news] index_type=", type(index), "index=", index)
                print("[es_search_news] _shards=", shards)
        except BadRequestError as e:
            print("[es_search_news] ES BadRequestError:", getattr(e, "info", e))
            raise

        hits = ((res.get("hits") or {}).get("hits") or []) if isinstance(res, dict) else []

        # 0 hit：有日期就不 fallback，直接回空
        if not hits:
            if date_from or date_to:
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

            dbg(">>>>>>>> [FALLBACK] using NON-SCRIPT query")
            body = build_fallback_query_body(es_query, must_high_value, must_selected, size)
            try:
                res = _safe_es_search(body, index=index)
                shards = (res or {}).get("_shards") if isinstance(res, dict) else None
                print("[es_search_news] index_type=", type(index), "index=", index)
                print("[es_search_news] _shards=", shards)
            except BadRequestError as e:
                print("[es_search_news] ES BadRequestError (fallback):", getattr(e, "info", e))
                raise
            hits = ((res.get("hits") or {}).get("hits") or []) if isinstance(res, dict) else []

        # === T4: 後處理：hits + evidence ===
        with log_duration("[es_search_news][T4] build_hits_and_evidence"):
            filtered_hits, evidence_snippets, syn_snippets = build_hits_and_evidence(
                hits,
                date_from=date_from,
                date_to=date_to,
                effective_terms=effective_terms,
                term_groups=term_groups,
                query_for_snippet=raw_query,
            )

        strong_snippets = [ev for ev in evidence_snippets if not ev.get("weak_evidence")]
        weak_snippets = [ev for ev in evidence_snippets if ev.get("weak_evidence")]

        log_total(
            "[es_search_news][TOTAL]",
            t_start,
            extra={"代理人ES文本查詢工具查詢字串": raw_query},
        )

        print(
            f"[es_search_news] query={raw_query!r}, es_query={es_query!r}, "
            f"hits={len(filtered_hits)}, "
            f"snippets_after_filter={len(evidence_snippets)}, "
            f"effective_terms={effective_terms}, "
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
