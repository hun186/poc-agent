# agent/tools_es.py
# 修正：
# - 移除 content_rt（避免超過 1,048,576 runtime string 限制）
# - fallback 改用非 script 查詢（simple_query_string + multi_match）
# - 日期過濾維持 nested range（穩定不噴錯）
# - 主題詞只在 subject_rt 做 wildcard（加分用，不做 must）

import os
import re
import json
from typing import Optional, List, Dict, Any
from elasticsearch import Elasticsearch, BadRequestError
from smolagents import Tool

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

def _safe_es_search(body: dict, *, allow_highlight_retry: bool = True):
    try:
        return ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
    except BadRequestError as e:
        info = str(getattr(e, "info", e))
        # 只要偵測到 highlighter 相關錯誤 → 移除 highlight 再試一次
        if allow_highlight_retry and ("max_analyzed_offset" in info or "highlight" in info):
            body2 = dict(body)
            body2.pop("highlight", None)
            return ES.search(index=ES_INDEX, body=body2, params={"error_trace": "true"})
        raise
        
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

'''
def _collect_timeline_dates(src: dict) -> list[str]:
    uniq, seen = [], set()
    for blk in (src.get("multidim_event_json") or []):
        for t in (blk or {}).get("Event_Timeline") or []:
            di = t.get("date_iso")
            if di and di not in seen:
                seen.add(di); uniq.append(di)
    return uniq
'''

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

'''
def _collect_timeline_dates_1124(src: dict) -> list[str]:
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
            di = t.get("date_iso")
            if di and di not in seen:
                seen.add(di); uniq.append(di)
    return uniq
'''

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
    # 例如 2025-06-27T00:00:00.000Z → 2025-06-27
    if len(di) >= 10:
        return di[:10]
    return None

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

# ===== ES 連線 =====
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = os.getenv("ES_INDEX", "news_test")
ES = Elasticsearch(ES_URL)

'''
# 只保留 subject_rt（安全、短字串）
RUNTIME_MAPPINGS = {
    "subject_rt": {
        "type": "keyword",
        "script": {"source": """
          def src = params._source;
          if (src == null) return;
          def c = src['communication'];
          if (c instanceof Map) {
            def s = c.get('subject');
            if (s != null) emit(s.toString());
          }
        """}
    }
}
'''
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
            "description": "返回筆數上限（1–60；預設 40）",
            "default": 40, "minimum": 1, "maximum": 60, "nullable": True
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
        }
    }
    #output_type = "string"
    # 讓代理拿到 Python dict（非字串），上層可直接 .get()
    #output_type = "json"
    output_type = "any"
    
    def _extract_topic_terms(self, q: str) -> List[str]:
        s = (q or "").strip()
        if not s:
            return []

        terms = set()

        # (1) 先抓「連續兩字以上」的中文詞
        zh_terms = re.findall(r'[\u4e00-\u9fff]{2,}', s)
        terms.update(zh_terms)

        # (2) 再抓數字 / 英數混合（長度 >= 2）
        #     e.g. "055", "DF-17", "BZK-005"
        for tok in re.split(r"\s+", s):
            tok = tok.strip(" ，,。.;；:：()（）[]【】")
            if not tok:
                continue
            # 年份 / 月份 之類不要當主題詞
            if re.fullmatch(r'(19|20)\d{2}', tok):
                continue
            if re.fullmatch(r'\d{1,2}', tok):     # 單純 1~2 位數字，當月/日處理，不當主題
                continue
            if len(tok) >= 2:
                terms.add(tok)

        # (3) 停用詞（盡量排掉不是「對象」的字）
        stop = {
            "請整理", "相關", "重點", "事件", "活動", "趨勢", "情勢", "狀況", "局勢",
            "偵獲", "情況", "情勢摘要", "活動特徵", "特徵",
            "變化", "綜整", "報告", "情監偵", "回報",
            "年", "月份", "月", "日",
            # 常見地理詞：這些多半是「範圍」，不是你要的「055 / 遼寧號」之類主體
            "台灣海峽", "臺灣海峽", "台海", "臺海",
            "東海", "南海", "黃海", "渤海"
        }
        return [t for t in terms if t not in stop]

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
        with_date: bool = True
    ) -> Dict[str, Any]:

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
            if date_from: rng["range"]["multidim_event_json.Event_Timeline.date_iso"]["gte"] = date_from
            if date_to:   rng["range"]["multidim_event_json.Event_Timeline.date_iso"]["lte"] = date_to
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
    
        shoulds = []
    
        # 1) 一般語義檢索
        shoulds.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "communication.subject^4",
                    "multidim_event_json.article_title^3",
                    "rawInfo.content^1.5",
                    "multidim_event_json.evidence_snippets.text"
                ],
                "type": "best_fields",
                "operator": "or"
            }
        })
        shoulds.append({
            "simple_query_string": {
                "query": q,
                "fields": [
                    "communication.subject^3",
                    "multidim_event_json.article_title^2",
                    "rawInfo.content",
                    "multidim_event_json.evidence_snippets.text"
                ],
                "default_operator": "and"
            }
        })
    
        # 2) 精準加分（keyword/wildcard）
        if q:
            def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
            # keyword 欄位：避免在 text 欄位 wildcard
            shoulds.append(wc("communication.subject.keyword", f"*{q}*"))
            shoulds.append(wc("multidim_event_json.article_title.raw", f"*{q}*"))
    
        # 3) 直接命中證據段落（nested + inner_hits）
        #    讓 citations 幾乎一定拿到 text/source_id/paragraph_id
        evidence_nested = {
            "nested": {
                "path": "multidim_event_json.evidence_snippets",
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {"multidim_event_json.evidence_snippets.text": q}},
                            {"match": {"multidim_event_json.evidence_snippets.text": {"query": q, "operator": "and"}}}
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
        shoulds.append(evidence_nested)
    
        base_bool = {
            "bool": {
                "should": shoulds,
                "minimum_should_match": 1,
                "filter": filters
            }
        }
    
        # 4) function_score：人審/AI 加權 +（可選）新鮮度
        functions = [
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
                "rawInfo.content",
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
                    # ⚠️ 移除 "rawInfo.content"
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
                      "nested": {"path": "multidim_event_json.Event_Timeline"}  # ← 修正這裡
                  }
                },
                {"importDT": {"order": "desc"}}
            ],
            "track_total_hits": True
        }
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
        size: Optional[int] = 5,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        selected_boost: Optional[float] = 6.0,
        high_value_boost: Optional[float] = 2.5,
        recency_boost: Optional[bool] = False,
        recency_field: Optional[str] = "importDT",
        recency_scale: Optional[str] = "30d",
    ):
        if not query:
            return {"hits": [], "error": "query is required"}
    
        # 1) 含日期的主查詢
        body = self._build_query_body(
            query, must_high_value, must_selected, size, date_from, date_to,
            selected_boost, high_value_boost, recency_boost, recency_field, recency_scale,
            with_date=True
        )
        try:
            #res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
            res = _safe_es_search(body)
        except BadRequestError as e:
            print("ES BadRequestError (with_date=True):", getattr(e, "info", e))
            raise
        hits = res.get("hits", {}).get("hits", [])
        '''
        #2) 拿掉日期再查 —— 若希望嚴格日期，可以註解掉整段
        if not hits and (date_from or date_to):
            body = self._build_query_body(
                query, must_high_value, must_selected, size, None, None,
                selected_boost, high_value_boost, recency_boost, recency_field, recency_scale,
                with_date=False
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
            body = self._build_nonscript_fallback_body(query, must_high_value, must_selected, size)
            try:
                #res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
                res = _safe_es_search(body)
            except BadRequestError as e:
                print("ES BadRequestError (fallback):", getattr(e, "info", e))
                raise
            hits = res.get("hits", {}).get("hits", [])
    
        # === parse（原邏輯，稍微加強 inner_hits 解析）===
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
            
        # ★ 新增：從 query 萃取主題詞
        topic_terms = self._extract_topic_terms(query or "")
        # 只要有主題詞，就要求 snippet 至少含一個主題詞（避免 DF-17 這種純「東海」噪音）
        def _match_topic(ev_text: str, subject: str | None, title: str | None) -> bool:
            if not topic_terms:
                return True  # 沒抓到主題詞就不做過濾，以免誤傷其他任務
            haystack = (ev_text or "") + " " + (subject or "") + " " + (title or "")
            return any(t in haystack for t in topic_terms)
        
        # === 這一段是新加的：組 evidence_snippets 給代理人用 ===
        evidence_snippets = []
        for h in out_hits:
            h_uuid = h.get("uuid")
            h_subject = h.get("subject")
            h_title = h.get("article_title")
            h_article_date = h.get("article_date_iso")
            h_event_dates = h.get("event_dates") or []

            for c in h.get("citations") or []:
                text = c.get("text")
                if not text:
                    continue

                # ★ 如果不含主題詞（例如只寫「DF-17 於東海」），就丟掉
                if not _match_topic(text, h_subject, h_title):
                    continue
                
                # 優先用 citation 自己的 date_iso，其次 hit 的 article_date_iso，再次 event_dates[0]
                di = c.get("date_iso") or h_article_date
                if not di and h_event_dates:
                    di = h_event_dates[0]
                
                norm_di = _normalize_iso_date(di)

                # ★ 加上 snippet 級日期過濾（對應你原本的 snippet_date 判斷）
                if norm_di:
                    if date_from and norm_di < date_from:
                        continue
                    if date_to and norm_di > date_to:
                        continue
                    
                ev = {
                    "uuid": h_uuid,
                    "text": text,
                    "article_date_iso": norm_di  or "",
                }

                if "paragraph_id" in c:
                    ev["paragraph_id"] = c["paragraph_id"]
                if "source_id" in c:
                    ev["source_id"] = c["source_id"]
                if h_subject:
                    ev["subject"] = h_subject
                if h_title:
                    ev["article_title"] = h_title

                evidence_snippets.append(ev)

        return {
            "hits": out_hits,
            "evidence_snippets": evidence_snippets
        }
        #return {"hits": out_hits}
        #return json.dumps({"hits": out_hits}, ensure_ascii=False)

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
    }
    #output_type = "string"
    #output_type = "json"
    output_type = "any"

    def forward(self, uuid: Optional[str] = None, k: Optional[int] = 10):
        if not uuid:
            return {"timeline": [], "error": "uuid is required"}
        try:
            res = _safe_es_search(
                {"size": 1, "query": {"term": {"uuid.keyword": uuid}}, "_source": ["multidim_event_json.Event_Timeline"]},
                allow_highlight_retry=False
            )
            
        except BadRequestError as e:
            print("ES BadRequestError (timeline):", getattr(e, "info", e)); raise

        items: List[Dict[str, Any]] = []
        '''
        hit = (res.get("hits", {}) or {}).get("hits", [])
        if hit:
            blocks = (hit[0].get("_source", {}) or {}).get("multidim_event_json", []) or []
            for b in blocks:
                for t in (b or {}).get("Event_Timeline", []) or []:
                    items.append({"date_iso": t.get("date_iso"),
                                  "date_raw": t.get("date_raw"),
                                  "description": t.get("description")})
        '''
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
        #return json.dumps({"timeline": items[: (k or 10)]}, ensure_ascii=False)
