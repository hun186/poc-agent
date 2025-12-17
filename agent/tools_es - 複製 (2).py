# agent/tools_es.py
import os
import re
import time
import unicodedata
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

from agent.es.synonyms import (
    #expand_manual_terms,
    extract_manual_terms_from_query,
)

from agent.es.query_terms import compute_effective_terms#,extract_topic_terms_rules


# ===== 統一的搜尋小幫手（處理 highlight 超長容錯） =====
ES_MAX_ANALYZED_OFFSET = int(os.getenv("ES_MAX_ANALYZED_OFFSET", "200000"))

def _as_blocks(md):
    """把 multidim_event_json 安全轉成 list[dict]。支援 str(json) / dict / list 三種情形。"""
    if not md:
        return []
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            return []
    if isinstance(md, dict):
        return [md]
    if isinstance(md, list):
        return [b for b in md if isinstance(b, dict)]
    return []

def _mark_synonym_hit(ev_text: str, effective_terms: Optional[List[str]]) -> List[str]:
    """
    回傳這段文字裡實際命中的同義詞（只做最簡單的字串包含）。
    用來標記 evidence_snippets 是被哪些 term 擊中的。
    """
    if not ev_text or not effective_terms:
        return []
    hits = []
    for t in effective_terms:
        if t and t in ev_text:
            hits.append(t)
    return hits


def _build_ev_from_hit_and_citation(
    h: dict,
    c: dict,
    date_from: str | None,
    date_to: str | None,
) -> dict | None:
    """
    把單一 hit + citation 轉成一筆 evidence_snippet：
    - 自動處理 date_iso / event_dates → article_date_iso
    - 套用 date_from / date_to 篩選
    - 帶上 uuid / subject / article_title / paragraph_id / source_id
    """
    h_uuid = h.get("uuid")
    h_subject = h.get("subject")
    h_title = h.get("article_title")
    h_article_date = h.get("article_date_iso")
    h_event_dates = h.get("event_dates") or []

    text = c.get("text")
    if not text:
        return None

    # 日期推斷：snippet 自己 → 文章日期 → 第一個 event_dates
    di = c.get("date_iso") or h_article_date
    if not di and h_event_dates:
        di = h_event_dates[0]
    norm_di = _normalize_iso_date(di)
    
    # 日期範圍過濾
    if norm_di:
        if date_from and norm_di < date_from:
            return None
        if date_to and norm_di > date_to:
            return None

    article_norm = _normalize_iso_date(h_article_date)
    snippet_norm = _normalize_iso_date(di)  # di 可以是 snippet 自己推斷出來的

    ev = {
        "uuid": h_uuid,
        "text": text,
        # snippet 自己使用的日期欄位（給 aggregate / agent 用）
        "date_iso": snippet_norm or article_norm or "",
        "article_date_iso": article_norm or snippet_norm or "",
        "subject": h_subject,
        "article_title": h_title,
    }
    if "paragraph_id" in c:
        ev["paragraph_id"] = c["paragraph_id"]
    if "source_id" in c:
        ev["source_id"] = c["source_id"]

    return ev
        
# ===== 簡易日期工具（原樣保留） =====
_YMD = re.compile(r'(?P<y>20\d{2}|19\d{2})[年/\-\.](?P<m>\d{1,2})[月/\-\.](?P<d>\d{1,2})日?')
_MD  = re.compile(r'(?P<m>\d{1,2})月(?P<d>\d{1,2})日')
_TODAY_D = re.compile(r'今[（(](?P<d>\d{1,2})[）)]日')
_PAREN_D = re.compile(r'[（(](?P<d>\d{1,2})日[）)]')

def _norm_date(y: int, m: int, d: int) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _parse_article_date_iso(raw: str) -> str | None:
    if not raw: return None
    m = _YMD.search(raw)
    if not m: return None
    return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

def _collect_timeline_dates(src: dict) -> list[str]:
    uniq, seen = [], set()
    blocks = _as_blocks((src or {}).get("multidim_event_json"))
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
            raw_di = t.get("date_iso")
            di = _normalize_iso_date(raw_di)
            if di and di not in seen:
                seen.add(di)
                uniq.append(di)
    return uniq

def _normalize_iso_date(di) -> str | None:
    """把 ES 裡的 date_iso 轉成 YYYY-MM-DD 字串，容錯 list / 含時間 / 含 Z。"""
    if not di:
        return None
    if isinstance(di, list):
        if not di:
            return None
        di = di[0]
    if not isinstance(di, str):
        return None

    # 正規化成前 10 碼
    if len(di) >= 10:
        candidate = di[:10]  # e.g. 2025-06-27 / XXXX-01-01
    else:
        return None

    # ★ 多一層：確認年份是 4 位數字，否則視為無效日期
    year_str = candidate[:4]
    if not year_str.isdigit():
        return None

    return candidate


def _infer_date_for_snippet(text: str, article_date_iso: str | None, timeline_dates: list[str]) -> str | None:
    if not text: return None
    m = _YMD.search(text)
    if m: return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))
    art_y = art_m = None
    if article_date_iso and len(article_date_iso) >= 10:
        art_y = int(article_date_iso[0:4]); art_m = int(article_date_iso[5:7])
    tl_years = sorted({int(di[0:4]) for di in timeline_dates if len(di) >= 10})
    m = _MD.search(text)
    if m:
        mm, dd = int(m.group('m')), int(m.group('d'))
        year = art_y or (tl_years[0] if len(tl_years) == 1 else None)
        if year: return _norm_date(year, mm, dd)
    m = _TODAY_D.search(text) or _PAREN_D.search(text)
    if m:
        dd = int(m.group('d'))
        if art_y and art_m: return _norm_date(art_y, art_m, dd)
        for di in timeline_dates:
            try:
                y, mm, d = int(di[0:4]), int(di[5:7]), int(di[8:10])
                if d == dd: return _norm_date(y, mm, d)
            except Exception: continue
    return None

def _make_fallback_snippet(text: str, q: str, width: int = 180) -> str | None:
    if not text:
        return None
    # 依 query 切詞（英文用空白；中文原樣），找第一個關鍵字出現點
    terms = [t for t in re.split(r"\s+", q or "") if t]
    positions = [text.find(t) for t in terms if t]
    pos = min([p for p in positions if p != -1] or [-1])
    if pos == -1:
        return text[:width]
    start = max(0, pos - width // 2)
    end = min(len(text), start + width)
    return text[start:end]

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
    #output_type = "string"
    # 讓代理拿到 Python dict（非字串），上層可直接 .get()
    #output_type = "json"
    output_type = "any"
    


    
    def _build_query_body(
        self,
        query: Optional[str],
        must_high_value: Optional[bool],
        must_selected: Optional[bool],
        size: Optional[int],
        date_from: Optional[str],
        date_to: Optional[str],
        selected_boost: Optional[float],
        high_value_boost: Optional[float],
        recency_boost: Optional[bool],
        recency_field: Optional[str],
        recency_scale: Optional[str],
        with_date: bool = True,
        effective_terms: Optional[List[str]] = None,   # 保留給後面 snippet 篩選用
        core_terms: Optional[List[str]] = None,        # 這三個只用在 ES 查詢加分
        syn_terms: Optional[List[str]] = None,
        all_terms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:

        core_terms = core_terms or []
        syn_terms = syn_terms or []
        all_terms = all_terms or []

        filters = []
        if must_high_value:
            filters.append({"term": {"ai.classLabels.highValue": True}})
        if must_selected:
            filters.append({"term": {"selectedMessage": True}})
    
        q = (query or "").strip()
        years_in_q = list(dict.fromkeys(re.findall(r'(?:19|20)\d{2}', q)))
    
        # 日期過濾：nested range
        if with_date and (date_from or date_to):
            rng = {"range": {"multidim_event_json.Event_Timeline.date_iso": {}}}
            if date_from:
                rng["range"]["multidim_event_json.Event_Timeline.date_iso"]["gte"] = date_from
            if date_to:
                rng["range"]["multidim_event_json.Event_Timeline.date_iso"]["lte"] = date_to
            filters.append({
                "nested": {
                    "path": "multidim_event_json.Event_Timeline",
                    "query": rng,
                    "score_mode": "none"
                }
            })
        elif with_date and years_in_q:
            year_should = [{
                "range": {"multidim_event_json.Event_Timeline.date_iso": {
                    "gte": f"{y}-01-01", "lte": f"{y}-12-31"
                }}
            } for y in years_in_q]
            filters.append({
                "nested": {
                    "path": "multidim_event_json.Event_Timeline",
                    "query": {"bool": {"should": year_should, "minimum_should_match": 1}},
                    "score_mode": "none"
                }
            })
    
        shoulds: List[Dict[str, Any]] = []

        # === ① 主力檢索欄位：以解析後欄位為主，原文 content 不參與第一階段 ===
        structured_fields_main = [
            # 事件與實體（主力）
            "multidim_event_json.Event.subject^8",
            "multidim_event_json.Event.object^7",
            "multidim_event_json.Event.location^7",
            "multidim_event_json.core_entities^7",
            "multidim_event_json.locations^7",

            # 時間線描述（次要，但常有關鍵敘述）
            "multidim_event_json.Event_Timeline.description^5",

            # 人物 / 涉入方
            "multidim_event_json.Person.name^5",
            "multidim_event_json.Person.role^4",
            "multidim_event_json.Involved_Parties.party_name^4",

            # 標題與主旨
            "multidim_event_json.article_title^4",
            "communication.subject^4",

            # 證據 snippet（給語意與說明用）
            "multidim_event_json.evidence_snippets.text^3",
        ]

        structured_fields_sqs = [
            # simple_query_string 版本，權重略降
            "multidim_event_json.Event.subject^5",
            "multidim_event_json.Event.object^4",
            "multidim_event_json.Event.location^4",
            "multidim_event_json.core_entities^4",
            "multidim_event_json.locations^4",
            "multidim_event_json.Event_Timeline.description^3",
            "multidim_event_json.Person.name^3",
            "multidim_event_json.Person.role^2",
            "multidim_event_json.Involved_Parties.party_name^2",
            "multidim_event_json.article_title^3",
            "communication.subject^3",
            "multidim_event_json.evidence_snippets.text^2",
        ]
        
        # 1) 一般語義檢索（第一階段只打解析後欄位，不打 rawInfo.content）
        shoulds.append({
            "multi_match": {
                "query": q,
                "fields": structured_fields_main,
                "type": "best_fields",
                "operator": "or"
            }
        })
        shoulds.append({
            "simple_query_string": {
                "query": q,
                "fields": structured_fields_sqs,
                "default_operator": "and"
            }
        })
    
        # 2) 精準加分（keyword/wildcard）
        if q:
            def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
            shoulds.append(wc("communication.subject.keyword", f"*{q}*"))
            shoulds.append(wc("multidim_event_json.article_title.raw", f"*{q}*"))
    
        # 3) 直接命中證據段落（nested + inner_hits）
        evidence_nested: Dict[str, Any] = {
            "nested": {
                "path": "multidim_event_json.evidence_snippets",
                "query": {
                    "bool": {
                        "should": [
                            {
                                "match_phrase": {
                                    "multidim_event_json.evidence_snippets.text": q
                                }
                            },
                            {
                                "match": {
                                    "multidim_event_json.evidence_snippets.text": {
                                        "query": q,
                                        "operator": "and"
                                    }
                                }
                            }
                        ],
                        "minimum_should_match": 1
                    }
                },
                "score_mode": "avg",
                "inner_hits": {
                    "name": "evi",
                    "size": 3,
                    "_source": [
                        "multidim_event_json.evidence_snippets.text",
                        "multidim_event_json.evidence_snippets.source_id",
                        "multidim_event_json.evidence_snippets.paragraph_id"
                    ],
                    "highlight": {
                        "fields": {
                            "multidim_event_json.evidence_snippets.text": {
                                "fragment_size": 180,
                                "number_of_fragments": 1
                            }
                        }
                    }
                }
            }
        }

        # ★ 在 nested 裡也加入 all_terms，強化 snippet 命中
        if all_terms:
            ev_should = evidence_nested["nested"]["query"]["bool"]["should"]
            for t in all_terms:
                ev_should.append({
                    "match_phrase": {
                        "multidim_event_json.evidence_snippets.text": t
                    }
                })
        
        # ★ 4) 人工同義詞 / 主題詞加分：rawInfo / subject / title
        if core_terms or syn_terms:
            entity_shoulds: List[Dict[str, Any]] = []
        
            # 核心主題詞：match_phrase（精準）
            for t in core_terms:
                entity_shoulds.append({"match_phrase": {"rawInfo.content": t}})
                entity_shoulds.append({"match_phrase": {"communication.subject": t}})
                entity_shoulds.append({"match_phrase": {"multidim_event_json.article_title": t}})
        
            # 同義詞：用 match（OR），當加分用
            for t in syn_terms:
                entity_shoulds.append({
                    "match": {
                        "rawInfo.content": {
                            "query": t,
                            "operator": "or"
                        }
                    }
                })
        
            if entity_shoulds:
                shoulds.append({
                    "bool": {
                        "should": entity_shoulds,
                        "minimum_should_match": 1
                    }
                })

        # 把 nested evidence 放進 should
        shoulds.append(evidence_nested)
    
        base_bool = {
            "bool": {
                "should": shoulds,
                "minimum_should_match": 1,
                "filter": filters
            }
        }
    
        # 4) function_score：人審/AI 加權 +（可選）新鮮度
        functions: List[Dict[str, Any]] = [
            {"filter": {"term": {"selectedMessage": True}}, "weight": (selected_boost or 6.0)},
            {"filter": {"term": {"ai.classLabels.highValue": True}}, "weight": (high_value_boost or 2.5)},
        ]
        if recency_boost:
            functions.append({"gauss": {(recency_field or "importDT"): {
                "scale": (recency_scale or "30d"),
                "decay": 0.5
            }}})
    
        body = {
            "size": size or 5,
            "_source": [
                "uuid",
                "communication.subject",
                #"rawInfo.content",
                "multidim_event_json.article_title",
                "multidim_event_json.evidence_snippets",
                "multidim_event_json.Event_Timeline",
                "selectedMessage",
                "ai.classLabels.highValue",
                "importDT",
                "update_time_ai"
            ],
            "query": {
                "function_score": {
                    "query": base_bool,
                    "boost_mode": "sum",
                    "score_mode": "sum",
                    "functions": functions
                }
            },
            "highlight": {
                "fields": {
                    "communication.subject": {"fragment_size": 100, "number_of_fragments": 1},
                    "multidim_event_json.article_title": {"fragment_size": 100, "number_of_fragments": 1}
                },
                "require_field_match": False
            },
            "sort": [
                "_score",
                {
                  "multidim_event_json.Event_Timeline.date_iso": {
                      "order": "desc",
                      "mode": "max",
                      "nested": {"path": "multidim_event_json.Event_Timeline"}
                  }
                },
                {"importDT": {"order": "desc"}}
            ],
            "track_total_hits": True
        }
        print("[_build_query_body] q=", q,
              "core_terms=", core_terms,
              "syn_terms=", syn_terms,
              "num_all_terms=", len(all_terms))
        return body


    def _build_nonscript_fallback_body(
            self,
            query: str,
            must_high_value: Optional[bool],
            must_selected: Optional[bool],
            size: Optional[int]
        ) -> Dict[str, Any]:
            filters: List[Dict[str, Any]] = []
            if must_high_value:
                filters.append({"term": {"ai.classLabels.highValue": True}})
            if must_selected:
                filters.append({"term": {"selectedMessage": True}})
        
            q = (query or "").strip()
            shoulds = [
                {"simple_query_string": {
                    "query": q,
                    "fields": ["communication.subject^3", "rawInfo.content", "multidim_event_json.article_title^2"]
                }},
                {"multi_match": {
                    "query": q,
                    "fields": ["communication.subject^2", "rawInfo.content", "multidim_event_json.evidence_snippets.text"]
                }}
            ]
            if q:
                def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
                shoulds.append(wc("communication.subject.keyword", f"*{q}*"))
                shoulds.append(wc("multidim_event_json.article_title.raw", f"*{q}*"))
        
            return {
                "size": size or 5,
                "_source": [
                    "uuid",
                    "communication.subject",
                    "rawInfo.content",
                    "multidim_event_json.evidence_snippets",
                    "multidim_event_json.article_title",
                    "multidim_event_json.Event_Timeline"
                ],
                "query": {"bool": {"should": shoulds, "minimum_should_match": 1, "filter": filters}},
                "highlight": {
                    "fields": {"rawInfo.content": {"fragment_size": 200, "number_of_fragments": 2}},
                    "require_field_match": False
                }
            }

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
        #print("before compute_effective_terms,raw_query",raw_query)

        # === T1: 主題詞/同義詞抽取時間 ===
        t_terms_start = time.perf_counter()
        #core_terms, grouped_syns, is_manual_entity_query = self._compute_effective_terms(raw_query)
        core_terms, grouped_syns, is_manual_entity_query, effective_terms, term_groups = compute_effective_terms(raw_query)
        t_terms_end = time.perf_counter()
        print(f"[es_search_news][T1] compute_effective_terms 花費 {t_terms_end - t_terms_start:.3f}s, "
              f"core_terms={core_terms}, num_groups={len(grouped_syns)}")
        #print("after _compute_effective_terms,core_terms, grouped_syns, is_manual_entity_query",core_terms, grouped_syns, is_manual_entity_query)
        '''
        # 2) 扁平化同義詞，建立 ES / snippet 共用的 effective_terms & term_groups
        # 2-1 扁平同義詞
        syn_terms_flat: List[str] = []
        for syns in grouped_syns.values():
            for s in syns:
                s = s.strip()
                if s and s not in syn_terms_flat:
                    syn_terms_flat.append(s)

        # 2-2 effective_terms = 核心 + 扁平同義詞（給 snippet 過濾 / fallback 用）
        effective_terms: List[str] = []
        seen_all: set[str] = set()
        for t in (core_terms or []) + syn_terms_flat:
            t = (t or "").strip()
            if t and t not in seen_all:
                seen_all.add(t)
                effective_terms.append(t)

        # 2-3 term_groups = 每一個核心一組（核心 + 其同義詞），給 _match_topic 用
        term_groups: List[set[str]] = []
        if core_terms:
            for core in core_terms:
                core = (core or "").strip()
                if not core:
                    continue
                g: set[str] = {core}
                for s in grouped_syns.get(core, []):
                    if isinstance(s, str):
                        ss = s.strip()
                        if ss:
                            g.add(ss)
                if g:
                    term_groups.append(g)
        else:
            # 沒有核心時，退回一組：全部 effective_terms
            if effective_terms:
                term_groups = [set(effective_terms)]

        # 2-4 ES nested evidence 用的 all_terms（= effective_terms）
        all_terms = list(effective_terms)
        '''
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
        t_body_start = time.perf_counter()
        body = self._build_query_body(
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

        # === T3: ES 查詢時間（含網路 + ES 計算）===
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
            body = self._build_nonscript_fallback_body(
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
        
        # === T4: Python 後處理時間（parse hits → evidence_snippets）===
        t_post_start = time.perf_counter()
        out_hits = []
        for h in hits:
            src = h.get("_source", {}) or {}

            # inner_hits（evidence_snippets）
            citations = []
            ih = (h.get("inner_hits") or {}).get("evi") or {}
            ih_hits = (ih.get("hits") or {}).get("hits") or []
            if ih_hits:
                for eh in ih_hits[:3]:
                    esrc = (eh.get("_source") or {})
                    txt = esrc.get("text")
                    sid = esrc.get("source_id")
                    pid = esrc.get("paragraph_id")
                    if not txt:
                        nested = esrc.get("multidim_event_json", {}).get("evidence_snippets", {})
                        txt = nested.get("text"); sid = nested.get("source_id"); pid = nested.get("paragraph_id")
                    if txt:
                        citations.append({"text": txt, "source_id": sid, "paragraph_id": pid})

            # 先取 raw 內文，後面 fallback 會用到
            raw_content = ((src.get("rawInfo") or {}).get("content") or "").strip()

            # ⚠️ 替換這一段：不要再用 highlight.rawInfo.content，改成用關鍵字窗格截取
            if not citations:
                snippet = _make_fallback_snippet(raw_content, query or "", width=180)
                if snippet:
                    citations.append({
                        "text": snippet,
                        "source_id": None,
                        "paragraph_id": None
                    })

            # 補日期（用 article_date_iso / timeline 推斷）
            article_date_iso = _parse_article_date_iso(raw_content)
            tl_dates = _collect_timeline_dates(src)
            
            # 如果 raw 解析不到日期，就用 timeline 的第一筆當作文章日期
            if (not article_date_iso) and tl_dates:
                article_date_iso = tl_dates[0]
                
            subject = (src.get("communication", {}) or {}).get("subject")  # ★ 新增：抓主標題
            article_title = (src.get("multidim_event_json") or {}).get("article_title")
            
            for c in citations:
                di = _infer_date_for_snippet(c.get("text") or "", article_date_iso, tl_dates)
                if di:
                    c["date_iso"] = di
                c["uuid"] = src.get("uuid")  # 讓每段 citation 都帶 uuid
                if subject:                                      # ★ 新增
                    c["subject"] = subject                       # ★ 新增
            # —— 追加：日期清洗（避免 0125/1992 這類超出分析範圍的雜訊）——
            def _is_valid_year(di: str) -> bool:
                try:
                    y = int(di[:4])
                    return 1900 <= y <= 2100
                except Exception:
                    return False
            
            for c in citations:
                di = c.get("date_iso")
                if di and not _is_valid_year(di):
                    c.pop("date_iso", None)
                    
            out_hits.append({
                "uuid": src.get("uuid"),
                "subject": (src.get("communication", {}) or {}).get("subject"),
                "score": h.get("_score"),
                "citations": citations[:8],
                "article_date_iso": article_date_iso,
                "event_dates": tl_dates[:20],
                "event_date_span": {"min": min(tl_dates), "max": max(tl_dates)} if tl_dates else None,
                "article_title": article_title,
                "selectedMessage": src.get("selectedMessage"),
                "highValue": (((src.get("ai") or {}).get("classLabels") or {}).get("highValue"))
            })
            
        # ★ 新版：從 query 萃取主題詞，採「規則 + 同義詞 + LLM（選配）」混合模式
        '''
        # (1) 原本 regex 版主題詞（較廣義，例如可能包含地名 / 角色）
        topic_terms = self._extract_topic_terms(query or "")

        # (2) 直接從 query 字串中掃 MANUAL_SYNONYMS（專門抓人工同義詞／型號）
        manual_terms_in_q = extract_manual_terms_from_query(query or "")
        '''
        # (1) 直接把 core_terms 當成「主題詞列表」
        #topic_terms = extract_topic_terms_rules(query or "")
        
        # (2) 直接從 query 字串中掃 MANUAL_SYNONYMS（專門抓人工同義詞／型號）
        manual_terms_in_q = extract_manual_terms_from_query(query or "")
        
        def _normalize_for_match(s: str) -> str:
            """
            用來做主題詞比對的輕量正規化：
            - NFKC：統一全形/半形
            - lower()：英文大小寫忽略
            - 統一各種破折號、短橫為 '-'
            - 把所有空白拿掉（含全形空白）
            """
            if not s:
                return ""
            s = unicodedata.normalize("NFKC", s)
            s = s.lower()
            s = re.sub(r"[‐-–—−]", "-", s)
            s = re.sub(r"\s+", "", s)
            return s
        
        
        def _match_topic(ev_text: str, subject: str | None, title: str | None) -> tuple[bool, set[str]]:
            """
            語意群組版主題詞過濾（加入正規化比對）：
        
            - term_groups: list[set[str]]，每一組是一個語意軸（例如「敘利亞」群、「化學武器」群）
            - 若 term_groups 為空 → 不過濾（避免誤殺其他任務）
            - 先計算每一組群組是否命中（group_hits），以及整體命中的字串集合 hit_terms
        
            判斷邏輯（人工同義詞 / 非人工同義詞一律相同）：
            - 若只有一個語意群組（例如只查「052D驅逐艦」或只查「化學武器」）：
                → 至少命中 1 組即可
            - 若有兩個以上語意群組（例如「東風15型導彈 宮古水道」）：
                → 至少要命中 2 組以上，才算同時滿足主體 + 地點/其他條件
            """
            if not term_groups:
                return True, set()
        
            haystack_raw = (ev_text or "") + " " + (subject or "") + " " + (title or "")
            haystack_norm = _normalize_for_match(haystack_raw)
        
            hit_terms: set[str] = set()
            group_hits = 0
        
            for g in term_groups:
                if not g:
                    continue
        
                g_hit: set[str] = set()
                for t in g:
                    if not t:
                        continue
                    t_norm = _normalize_for_match(t)
                    if t_norm and t_norm in haystack_norm:
                        g_hit.add(t)
        
                if g_hit:
                    group_hits += 1
                    hit_terms |= g_hit
        
            if group_hits == 0:
                return False, set()
        
            num_groups = len(term_groups)
    
            # 單一語意軸：命中至少一組就可
            if num_groups <= 1:
                return True, hit_terms
    
            # 兩軸：全部都要命中（等於 AND）
            if num_groups == 2:
                return (group_hits == 2), hit_terms
    
            # 三軸：全部都要命中，避免「只中敘利亞+化武」卻沒「調查」也通過
            if num_groups == 3:
                return (group_hits == 3), hit_terms
    
            # 四軸以上：至少命中 3 軸，避免太嚴格直接篩成 0
            if group_hits >= 3:
                return True, hit_terms
    
            return False, hit_terms
                
        # === 組 evidence_snippets 給代理人用（加入 snippet 級日期過濾 + 主題詞過濾）===
        evidence_snippets = []
        for h in out_hits:
            h_subject = h.get("subject")
            h_title = h.get("article_title")
        
            for c in h.get("citations") or []:
                ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                if ev is None:
                    continue
        
                text = ev["text"]

                # ★ 語意群組過濾：人工同義詞查詢 vs 非人工同義詞查詢
                ok, hit_terms = _match_topic(text, h_subject, h_title)
                if not ok:
                    continue

                # 把實際命中的關鍵詞（跨群組）寫回去
                if hit_terms:
                    ev["synonym_hits"] = list(hit_terms)

                evidence_snippets.append(ev)



        # 若 evidence_snippets 被過濾到 0，但 hits 還很多，保險起見回退成「每個 hit 至少取一段」
        # ★ 只有在「沒有抓到任何有效主題詞」時，才啟用這個 fallback（避免把「敘利亞 + 化武」這種噪音塞回來）
        if not evidence_snippets and out_hits and not effective_terms:
            for h in out_hits[:10000]:  # 控制數量
                for c in (h.get("citations") or [])[:1]:
                    ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                    if ev is None:
                        continue
                    evidence_snippets.append(ev)
        '''
        # === 補救：有 hits、有主題詞，卻沒有任何 snippet ===
        if not evidence_snippets and out_hits and effective_terms:
            # 只做一次重試，避免無限迴圈
            expanded = _expand_query_synonyms_llm(raw_query, effective_terms)
            expanded = [t for t in expanded if isinstance(t, str) and t.strip()]
            if expanded:
                # 合併原本 + 新同義詞
                extended_terms = list({*effective_terms, *expanded})
                print(f"[es_search_news] 同義詞補救：effective_terms 擴充為 {extended_terms}")

                new_snippets = []
                for h in out_hits:
                    h_subject = h.get("subject")
                    h_title = h.get("article_title")

                    for c in h.get("citations") or []:
                        ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                        if ev is None:
                            continue

                        text = ev["text"]
                        haystack = (text or "") + " " + (h_subject or "") + " " + (h_title or "")
                        # 用 extended_terms 重新判斷（比 _match_topic 寬鬆一點）
                        hit_terms = {t for t in extended_terms if t and t in haystack}
                        if not hit_terms:
                            continue

                        ev["synonym_hits"] = list(hit_terms)
                        new_snippets.append(ev)

                if new_snippets:
                    # 視需要可 truncate，例如 [:200]
                    evidence_snippets = new_snippets
        '''
        if not evidence_snippets and out_hits and effective_terms:
            print("[es_search_news] snippet 為 0，改用寬鬆條件重試（不再打 LLM）")
            new_snippets = []
            for h in out_hits:
                h_subject = h.get("subject")
                h_title = h.get("article_title")
        
                for c in h.get("citations") or []:
                    ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                    if ev is None:
                        continue
        
                    text = ev["text"]
                    haystack = (text or "") + " " + (h_subject or "") + " " + (h_title or "")
                    hit_terms = {t for t in effective_terms if t and t in haystack}
                    if not hit_terms:
                        continue
        
                    ev["synonym_hits"] = list(hit_terms)
                    new_snippets.append(ev)
        
            if new_snippets:
                evidence_snippets = new_snippets
        # 只保留「至少有一段 evidence_snippet」的文件
        if evidence_snippets:
            kept_uuids = {ev["uuid"] for ev in evidence_snippets if ev.get("uuid")}
            filtered_hits = [h for h in out_hits if h.get("uuid") in kept_uuids]
        else:
            filtered_hits = out_hits  # 沒 snippet 就維持原樣（通常 already empty）

        syn_snippets = sum(
            1 for ev in evidence_snippets
            if ev.get("synonym_hits")
        )
        t_post_end = time.perf_counter()
        print(f"[es_search_news][T4] Python 後處理（parse hits + evidence_snippets）花費 "
              f"{t_post_end - t_post_start:.3f}s, "
              f"hits={len(out_hits)}, evidence_snippets={len(evidence_snippets)}")

        # === T5: 整體總時間 ===
        t_end = time.perf_counter()
        print(f"[es_search_news][TOTAL] query={raw_query!r}, total={t_end - t_start:.3f}s")

        print(
            f"[es_search_news] query={raw_query!r}, es_query={es_query!r}, "
            f"hits={len(out_hits)}, "
            f"hits_after_filter={len(filtered_hits)}, "   # 新增一個統計
            f"snippets_before_filter={sum(len(h.get('citations', [])) for h in out_hits)}, "
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
    
    