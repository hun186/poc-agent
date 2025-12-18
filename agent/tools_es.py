# agent/tools_es.py
import os
import time
import json
from typing import Optional, List, Dict, Any
from elasticsearch import BadRequestError
from elasticsearch import NotFoundError
from smolagents import Tool
from agent.es.es_client import (
    ES,
    safe_search as _safe_es_search,
    resolve_index as _resolve_es_index,
)

from agent.es.query_terms import compute_effective_terms#,extract_topic_terms_rules
from agent.es.evidence import build_hits_and_evidence, _as_blocks
from agent.es.query_body import (
    build_main_query_body,
    build_fallback_query_body,
)
from agent.utils.profiler import log_duration, log_total

class ESSearchNews(Tool):
    name = "es_search_news"
    description = (
        "BM25 + nested 日期過濾；回傳證據段落、uuid、subject、分數等。"
        #"回傳結果中的 evidence_snippets 欄位，已經是後續統計與趨勢分析可直接使用的最終片段。"
        #"若之後要做時間統計，請直接把 es_search_news 回傳的 evidence_snippets 整個 list"
        #"傳給 aggregate_month_quarter，不要再以關鍵字或其它條件對 evidence_snippets 做二次過濾，"
        #"以免誤將清單過濾成空而讓統計結果變成 0。"
    )
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
    # 讓代理拿到 Python dict（非字串），上層可直接 .get()
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
        index_hint: Optional[str] = None,   # ★ 新增
    ):
        # 依 LLM 分流 or env 決定實際 index
        
        # === T0: 整體開始時間 ===
        t_start = time.perf_counter()
        
        max_size = int(os.getenv("ES_MAX_SIZE", "10000"))
        try:
            req_size = int(size) if size is not None else max_size
        except Exception:
            req_size = max_size
        size = max(1, min(req_size, max_size))
        if not query:
            return {"hits": [], "error": "query is required"}
        '''
        # 🔴 這一段是關鍵：強制統一實際使用的 size
        max_size = int(os.getenv("ES_MAX_SIZE", "10000"))  # 你可以改成 100、200 等
        try:
            req_size = int(size) if size is not None else max_size
        except Exception:
            req_size = max_size
        # clamp 到 [1, max_size]
        size = max(1, min(req_size, max_size))
        '''
        #print("in forward, query at begining", query)
        raw_query = (query or "").strip()
        #print("in forward, raw_query at begining", raw_query)
        
        # 這裡不再從 query 抽 ES_INDEX_HINT，完全靠參數分流
        #print("index_hint",index_hint)
        final_hint = index_hint  # 可以是 None 或 "a,b,c"
        #print("final_hint",final_hint)
        index = _resolve_es_index(final_hint)
        #print("[ESSearchNews.forward] index =", index, "query =", raw_query)
        
        # 乾淨 query 就是原本的 raw_query
        query = raw_query
    
        print("in ESSearchNews.forward, index =", index, "query =", query)
        
        # 1) 抽核心主題詞 + 群組同義詞（含人工同義詞家族展開）

        # === T1: 主題詞/同義詞抽取時間 ===
        #t_terms_start = time.perf_counter()
        #core_terms, grouped_syns, is_manual_entity_query, manual_terms_in_q, effective_terms, term_groups = compute_effective_terms(raw_query)
        #t_terms_end = time.perf_counter()
        #print(f"[es_search_news][T1] compute_effective_terms 花費 {t_terms_end - t_terms_start:.3f}s, "
        #      f"core_terms={core_terms}, num_groups={len(grouped_syns)}")

        with log_duration("[es_search_news][T1] compute_effective_terms"):
            core_terms, grouped_syns, is_manual_entity_query, manual_terms_in_q, effective_terms, term_groups = compute_effective_terms(raw_query)
        
        print(f"[es_search_news] core_terms={core_terms}, num_groups={len(grouped_syns)}")

        # 2) 扁平化同義詞（僅供 ES 查詢加分用；effective_terms / term_groups 已由 compute_effective_terms 給出）
        syn_terms_flat: List[str] = []
        seen_syn: set[str] = set()
        for syns in grouped_syns.values():
            for s in syns:
                if not isinstance(s, str):
                    continue
                s = s.strip()
                if not s or s in seen_syn:
                    continue
                seen_syn.add(s)
                syn_terms_flat.append(s)
        
        # ES nested evidence 用的 all_terms（給 evidence_snippets 裡的 nested match）
        all_terms = list(effective_terms or [])
        
        es_query = raw_query
        # === T2: 組 query body 時間 ===
        '''
        t_body_start = time.perf_counter()
        #body = self._build_query_body(
        body = build_main_query_body(
            es_query,
            must_high_value, must_selected, size, date_from, date_to,
            selected_boost, high_value_boost, recency_boost, recency_field, recency_scale,
            with_date=True,
            effective_terms=effective_terms,   # 主要給後面 log / fallback 用
            core_terms=core_terms,             # 精準加分 match_phrase
            syn_terms=syn_terms_flat,          # 同義詞加分 match
            all_terms=all_terms,               # nested evidence_snippets 裡的 match_phrase
        )
        t_body_end = time.perf_counter()
        print(f"[es_search_news][T2] _build_query_body 花費 {t_body_end - t_body_start:.3f}s")
        '''
        with log_duration("[es_search_news][T2] build_main_query_body"):
            body = build_main_query_body(
                es_query,
                must_high_value, must_selected, size, date_from, date_to,
                selected_boost, high_value_boost, recency_boost, recency_field, recency_scale,
                with_date=True,
                effective_terms=effective_terms,
                core_terms=core_terms,
                syn_terms=syn_terms_flat,
                all_terms=all_terms,
            )
            
        # === T3: ES 查詢時間（含網路 + ES 計算）===
        '''
        t_es_start = time.perf_counter()
        try:
            #res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
            res = _safe_es_search(body, index=index)
        except BadRequestError as e:
            print("ES BadRequestError (with_date=True):", getattr(e, "info", e))
            raise
        t_es_end = time.perf_counter()
        es_took = (res.get("took") if isinstance(res, dict) else None)
        print(f"[es_search_news][T3] _safe_es_search 花費 {t_es_end - t_es_start:.3f}s, "
              f"ES took={es_took} ms, index={index}, size={size}")
        '''
        try:
            with log_duration("[es_search_news][T3] _safe_es_search",
                              extra={"index": index, "size": size}):
                res = _safe_es_search(body, index=index)
        except BadRequestError as e:
            print("ES BadRequestError (with_date=True):", getattr(e, "info", e))
            raise
        
        es_took = (res.get("took") if isinstance(res, dict) else None)
        print(f"[es_search_news] ES took={es_took} ms, index={index}, size={size}")
        hits = res.get("hits", {}).get("hits", [])
        '''
        #2) 拿掉日期再查 —— 若希望嚴格日期，可以註解掉整段
        if not hits and (date_from or date_to):
            body = self._build_query_body(
                query, must_high_value, must_selected, size, None, None,
                selected_boost, high_value_boost, recency_boost, recency_field, recency_scale,
                with_date=False,
                effective_terms=effective_terms,
            )
            try:
                #res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
                res = _safe_es_search(body)
            except BadRequestError as e:
                print("ES BadRequestError (with_date=False):", getattr(e, "info", e))
                raise
            hits = res.get("hits", {}).get("hits", [])
        '''
        # 3) 仍 0 筆 → 非 script fallback
        if not hits:
            # 👇 如果有指定日期，就不要再 fallback，直接回空結果
            if date_from or date_to:
                return {
                    "hits": [],
                    "evidence_snippets": []
                }
            print(">>>>>>>> [FALLBACK] using NON-SCRIPT query")
            body = build_fallback_query_body(
                es_query, must_high_value, must_selected, size
            )
            try:
                #res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
                res = _safe_es_search(body, index=index)
            except BadRequestError as e:
                print("ES BadRequestError (fallback):", getattr(e, "info", e))
                raise
            hits = res.get("hits", {}).get("hits", [])
    
        # === parse（原邏輯，稍微加強 inner_hits 解析）===
        
        # === T4: Python 後處理時間（parse hits + evidence_snippets）===
        '''
        t_post_start = time.perf_counter()
        filtered_hits, evidence_snippets, syn_snippets = build_hits_and_evidence(
            hits,
            date_from=date_from,
            date_to=date_to,
            effective_terms=effective_terms,
            term_groups=term_groups,
            query_for_snippet=query or "",
        )
        t_post_end = time.perf_counter()
        print(
            f"[es_search_news][T4] Python 後處理（parse hits + evidence_snippets）花費 "
            f"{t_post_end - t_post_start:.3f}s, "
            f"hits={len(filtered_hits)}, evidence_snippets={len(evidence_snippets)}"
        )
        '''
        with log_duration("[es_search_news][T4] build_hits_and_evidence"):
            filtered_hits, evidence_snippets, syn_snippets = build_hits_and_evidence(
                hits,
                date_from=date_from,
                date_to=date_to,
                effective_terms=effective_terms,
                term_groups=term_groups,
                query_for_snippet=query or "",
            )
        
        print(
            f"[es_search_news] hits={len(filtered_hits)}, "
            f"evidence_snippets={len(evidence_snippets)}"
        )
        # === T5: 整體總時間 ===
        #t_end = time.perf_counter()
        #print(f"[es_search_news][TOTAL] query={raw_query!r}, total={t_end - t_start:.3f}s")

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
        # ★ 統一把這輪查詢的關鍵字／同義詞／時間範圍整理成 query_meta
        query_meta = {
            # 原始使用者查詢
            "query": raw_query,

            # 實際 ES 用的查詢字串（目前就是 raw_query，你之後要加特殊語法也可以改這裡）
            "es_query": es_query,

            # 主題相關詞
            #"topic_terms": topic_terms,           # 規則抽出來的主題詞
            "core_terms": core_terms,             # LLM + 人工同義詞家族合併後的代表詞
            "syn_terms": syn_terms_flat,          # 扁平化的同義詞
            "effective_terms": effective_terms,   # 核心 + 同義詞（給 snippet 過濾 / fallback 用）

            # 查詢型態資訊
            "manual_terms_in_q": manual_terms_in_q,
            "is_manual_entity_query": is_manual_entity_query,
            # term_groups 是 list[set]，轉成 list[list] 比較好序列化
            "term_groups": [sorted(list(g)) for g in term_groups],

            # 時間條件（和 aggregate 的 time_range 對應）
            "date_from": date_from,
            "date_to": date_to,
        }
        print("[es_search_news] query_meta =", json.dumps(query_meta, ensure_ascii=False))
        return {
            "hits": filtered_hits,
            "evidence_snippets": evidence_snippets,
            "query_meta": query_meta,   # ★ 新增
        }


class ESTimeline(Tool):
    name = "es_timeline"
    description = "讀取指定 uuid 的 multidim_event_json.Event_Timeline，回傳依日期排序的 {date_iso, date_raw, description}"
    inputs = {
        "uuid": {
            "type": "string",
            "description": "要讀取之文件的 uuid（對應索引中的 uuid.keyword）",
            "nullable": True
        },
        "k": {
            "type": "integer",
            "description": "最多回傳多少筆時間線事件（1–60；預設 40）",
            "default": 40,
            "minimum": 1,
            "maximum": 60,
            "nullable": True
        },
        # ★ 新增：和 es_search_news 一樣吃分流 hint
        "index_hint": {
            "type": "string",
            "description": "由 LLM 分流傳入的索引提示字串；若未提供則使用環境變數 ES_INDEX",
            "nullable": True
        },
    }
    #output_type = "string"
    #output_type = "json"
    output_type = "any"

    def forward(
        self,
        uuid: Optional[str] = None,
        k: Optional[int] = 10,
        index_hint: Optional[str] = None,   # ★ 新增
    ):
        if not uuid:
            return {"timeline": [], "error": "uuid is required"}

        # 依 LLM 分流或 env 決定實際查詢 index
        index = _resolve_es_index(index_hint)
        # （非必要，但 debug 很有用）
        # print(f"[es_timeline] using ES index: {index}")

        try:
            res = _safe_es_search(
                {
                    "size": 1,
                    "query": {"term": {"uuid.keyword": uuid}},
                    "_source": ["multidim_event_json.Event_Timeline"],
                },
                index=index,
                allow_highlight_retry=False,
            )
        except BadRequestError as e:
            print("ES BadRequestError (timeline):", getattr(e, "info", e))
            raise

        items: List[Dict[str, Any]] = []
        hit = (res.get("hits", {}) or {}).get("hits", [])
        if hit:
            src0 = (hit[0].get("_source", {}) or {})
            blocks = _as_blocks(src0.get("multidim_event_json"))
            for b in blocks:
                ets = b.get("Event_Timeline") or []
                if isinstance(ets, str):
                    try:
                        ets = json.loads(ets)
                    except Exception:
                        ets = []
                if isinstance(ets, dict):
                    ets = [ets]
                for t in ets:
                    if not isinstance(t, dict):
                        continue
                    items.append({
                        "date_iso": t.get("date_iso"),
                        "date_raw": t.get("date_raw"),
                        "description": t.get("description")
                    })
        items = [i for i in items if i.get("date_iso")]
        items.sort(key=lambda x: x["date_iso"])
        return {"timeline": items[: (k or 10)]}

class ESFetchDocById(Tool):
    """
    依 uuid 從 Elasticsearch 撈出「單篇完整文件」，主要提供風格學習 / 公文範例用。

    - 預期 index 內有欄位 uuid（或 _id 就是 uuid）
    - 內文欄位預設用 text_field 指定，預設抓 rawInfo.content
    """
    name = "es_fetch_doc_by_id"
    description = "依 uuid 從 Elasticsearch 撈出完整文件內文，供風格寫作或報告範例參考。"

    inputs = {
        "uuid": {
            "type": "string",
            "description": "文件的 uuid 欄位值（對應索引中的 uuid 或 _id）。",
        },
        "index_hint": {
            "type": "string",
            "description": "可選：指定要查的 index（或多個 index，用逗號分隔）；未提供則走預設 ES_INDEX。",
            "nullable": True,
        },
        "text_field": {
            "type": "string",
            "description": (
                "可選：主要內文欄位名稱，例如 'rawInfo.content'、'content'、"
                "'doc_text'；預設為 'rawInfo.content'。"
            ),
            "nullable": True,
        },
    }

    output_type = "any"

    outputs = {
        "uuid": {"type": "string"},
        "index": {"type": "string"},
        "full_text": {"type": "string"},
        "source": {"type": "object"},
    }

    def __init__(self):
        super().__init__()
        self.es = ES

    def forward(
        self,
        uuid: str,
        index_hint: Optional[str] = None,
        text_field: Optional[str] = "rawInfo.content",
    ) -> Dict[str, Any]:
        if not uuid:
            return {
                "uuid": "",
                "index": "",
                "full_text": "",
                "source": {},
                "error": "uuid is required",
            }

        # 1) 決定要查的 index
        index = _resolve_es_index(index_hint)

        src = None
        hit_index = None

        # === 2) 優先嘗試：當 uuid 就是 _id，用 GET 直接拿 ===
        try:
            resp = self.es.get(index=index, id=uuid, _source=True)
            if resp and resp.get("found"):
                src = resp.get("_source") or {}
                hit_index = resp.get("_index", str(index))
        except NotFoundError:
            # 找不到就當沒事，改用 term 查 uuid
            pass
        except Exception as e:
            # 其他錯誤印出來，但不要整個炸掉
            print(f"[ESFetchDocById] get(id=uuid) error: {e}")

        # === 3) 若 GET 沒拿到，再 fallback 用 uuid 欄位 term 搜尋 ===
        if src is None:
            query = {
                "term": {
                    # ⚠ 關鍵：不用 uuid.keyword，只用 uuid，本身就適用 keyword / text 兩種 mapping
                    "uuid": uuid
                }
            }
            try:
                resp = self.es.search(
                    index=index,
                    size=1,
                    query=query,
                    _source=True,
                )
                hits = (resp.get("hits") or {}).get("hits") or []
                if hits:
                    hit = hits[0]
                    src = hit.get("_source") or {}
                    hit_index = hit.get("_index", str(index))
            except Exception as e:
                print(f"[ESFetchDocById] search(uuid) error: {e}")
                return {
                    "uuid": uuid,
                    "index": str(index),
                    "full_text": "",
                    "source": {},
                    "error": str(e),
                }

        # 仍然沒資料
        if not src:
            return {
                "uuid": uuid,
                "index": str(index),
                "full_text": "",
                "source": {},
            }

        # === 4) 取主要內文 ===
        tf = text_field or "rawInfo.content"

        def _dot_get(d: dict, path: str):
            cur = d
            for p in path.split("."):
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(p)
                if cur is None:
                    return None
            return cur

        full_text = (
            _dot_get(src, tf)
            or _dot_get(src, "rawInfo.content")
            or src.get("content")
            or src.get("doc_text")
            or ""
        )

        if not isinstance(full_text, str):
            full_text = str(full_text)

        return {
            "uuid": uuid,
            "index": hit_index or str(index),
            "full_text": full_text,
            "source": src,
        }
    
    