# agent/tools_es.py
# 修正：
# - 移除 content_rt（避免超過 1,048,576 runtime string 限制）
# - fallback 改用非 script 查詢（simple_query_string + multi_match）
# - 日期過濾維持 nested range（穩定不噴錯）
# - 主題詞只在 subject_rt 做 wildcard（加分用，不做 must）

import os
import re
from typing import Optional, List, Dict, Any
from elasticsearch import Elasticsearch, BadRequestError
from smolagents import Tool

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
    for blk in (src.get("multidim_event_json") or []):
        for t in (blk or {}).get("Event_Timeline") or []:
            di = t.get("date_iso")
            if di and di not in seen:
                seen.add(di); uniq.append(di)
    return uniq

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

# ===== ES 連線 =====
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = os.getenv("ES_INDEX", "news_test")
ES = Elasticsearch(ES_URL)

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
                "description": "僅回傳 ai.classLabels.highValue=true 的文件（預設 True）",
                "default": True,
                "nullable": True
            },
            "lang": {
                "type": "string",
                "description": "保留參數；目前不做語言過濾（忽略）",
                "default": None,
                "nullable": True
            },
            "size": {
                "type": "integer",
                "description": "返回筆數上限（1–20；預設 5）",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "nullable": True
            },
            "date_from": {
                "type": "string",
                "description": "ISO 起始日期（YYYY-MM-DD）；用於 nested range 過濾 Event_Timeline.date_iso",
                "nullable": True
            },
            "date_to": {
                "type": "string",
                "description": "ISO 結束日期（YYYY-MM-DD）；用於 nested range 過濾 Event_Timeline.date_iso",
                "nullable": True
            },
        }
    output_type = "string"

    def _extract_topic_terms(self, q: str) -> List[str]:
        s = (q or "")
        terms = {m for m in re.findall(r'[\u4e00-\u9fff]{2,}', s)}
        stop = {"請整理", "相關", "重點", "事件", "年", "月份", "月", "日"}
        return [t for t in terms if t not in stop]

    def _build_query_body(
        self, query: Optional[str], must_high_value: Optional[bool], lang: Optional[str],
        size: Optional[int], date_from: Optional[str], date_to: Optional[str], with_date: bool = True
    ) -> Dict[str, Any]:

        filters: List[Dict[str, Any]] = []
        if must_high_value:
            filters.append({"term": {"ai.classLabels.highValue": True}})

        q = (query or "").strip()
        years_in_q = list(dict.fromkeys(re.findall(r'(?:19|20)\\d{2}', q)))

        # 日期：nested range（安全）
        if with_date and (date_from or date_to):
            rng = {"range": {"multidim_event_json.Event_Timeline.date_iso": {}}}
            if date_from: rng["range"]["multidim_event_json.Event_Timeline.date_iso"]["gte"] = date_from
            if date_to:   rng["range"]["multidim_event_json.Event_Timeline.date_iso"]["lte"] = date_to
            filters.append({
                "nested": {"path": "multidim_event_json.Event_Timeline", "query": rng, "score_mode": "none"}
            })
        elif with_date and years_in_q:
            year_should = [{
                "range": {"multidim_event_json.Event_Timeline.date_iso": {"gte": f"{y}-01-01", "lte": f"{y}-12-31"}}
            } for y in years_in_q]
            filters.append({
                "nested": {"path": "multidim_event_json.Event_Timeline",
                           "query": {"bool": {"should": year_should, "minimum_should_match": 1}},
                           "score_mode": "none"}
            })

        # should：主題詞只在 subject_rt，加分用
        topic_should = []
        for kw in self._extract_topic_terms(q):
            topic_should.append({"wildcard": {"subject_rt": {"value": f"*{kw}*"}}})

        def wc(field, pat): return {"wildcard": {field: {"value": pat}}}

        should_clauses: List[Dict[str, Any]] = []
        should_clauses += topic_should
        should_clauses.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "communication.subject^3",
                    "rawInfo.content^1.5",
                    "multidim_event_json.article_title^2",
                    "multidim_event_json.evidence_snippets.text"
                ],
                "type": "best_fields",
                "operator": "or"
            }
        })
        should_clauses.append({
            "query_string": {
                "query": q,
                "fields": [
                    "communication.subject^4",
                    "multidim_event_json.article_title^3",
                    "rawInfo.content"
                ],
                "default_operator": "AND",
                "analyze_wildcard": True
            }
        })
        if q:
            should_clauses.append(wc("communication.subject", f"*{q}*"))
            should_clauses.append(wc("rawInfo.content",     f"*{q}*"))

        body = {
            "size": size or 5,
            "track_total_hits": True,
            "_source": [
                "uuid",
                "communication.subject",
                "rawInfo.content",
                "multidim_event_json.evidence_snippets",
                "multidim_event_json.article_title",
                "multidim_event_json.Event_Timeline"
            ],
            "runtime_mappings": RUNTIME_MAPPINGS,  # 只含 subject_rt，已安全
            "query": {
                "bool": {
                    "should": should_clauses + [
                        {"wildcard": {"subject_rt": {"value": f"*{q}*"}}},
                    ],
                    "minimum_should_match": 1,
                    "filter": filters
                }
            },
            "highlight": {
                "fields": {
                    "rawInfo.content": {"fragment_size": 200, "number_of_fragments": 2},
                    "communication.subject": {"fragment_size": 100, "number_of_fragments": 1},
                    "multidim_event_json.article_title": {"fragment_size": 100, "number_of_fragments": 1}
                },
                "require_field_match": False
            }
        }
        return body

    def _build_nonscript_fallback_body(
        self, query: str, must_high_value: Optional[bool], lang: Optional[str], size: Optional[int]
    ) -> Dict[str, Any]:
        """不使用 script/RuntimeField 的保底查詢：最寬鬆但不會炸。"""
        filters: List[Dict[str, Any]] = []
        if must_high_value:
            filters.append({"term": {"ai.classLabels.highValue": True}})

        q = (query or "").strip()
        shoulds = [
            {"simple_query_string": {
                "query": q, "fields": ["communication.subject^3", "rawInfo.content", "multidim_event_json.article_title^2"]
            }},
            {"multi_match": {
                "query": q,
                "fields": ["communication.subject^2", "rawInfo.content", "multidim_event_json.evidence_snippets.text"]
            }}
        ]
        if q:
            def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
            shoulds.append(wc("communication.subject", f"*{q}*"))
            shoulds.append(wc("rawInfo.content", f"*{q}*"))

        body = {
            "size": size or 5,
            "_source": [
                "uuid",
                "communication.subject",
                "rawInfo.content",
                "multidim_event_json.evidence_snippets",
                "multidim_event_json.article_title",
                "multidim_event_json.Event_Timeline"
            ],
            # 注意：fallback 不帶 runtime_mappings，避免任何 runtime 風險
            "query": {"bool": {"should": shoulds, "minimum_should_match": 1, "filter": filters}},
            "highlight": {
                "fields": {"rawInfo.content": {"fragment_size": 200, "number_of_fragments": 2}},
                "require_field_match": False
            }
        }
        return body

    def forward(
        self, query: Optional[str] = None, must_high_value: Optional[bool] = True, lang: Optional[str] = "C",
        size: Optional[int] = 5, date_from: Optional[str] = None, date_to: Optional[str] = None,
    ):
        if not query:
            return {"hits": [], "error": "query is required"}

        # 1) 含日期的主查詢
        body = self._build_query_body(query, must_high_value, lang, size, date_from, date_to, with_date=True)
        try:
            res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
        except BadRequestError as e:
            print("ES BadRequestError (with_date=True):", getattr(e, "info", e))
            raise
        hits = res.get("hits", {}).get("hits", [])

        # 2) 拿掉日期再查
        if not hits and (date_from or date_to):
            body = self._build_query_body(query, must_high_value, lang, size, None, None, with_date=False)
            try:
                res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
            except BadRequestError as e:
                print("ES BadRequestError (with_date=False):", getattr(e, "info", e)); raise
            hits = res.get("hits", {}).get("hits", [])

        # 3) 仍 0 筆 → 非 script fallback（避免 runtime 上限）
        if not hits:
            print(">>>>>>>> [FALLBACK] using NON-SCRIPT query")
            body = self._build_nonscript_fallback_body(query, must_high_value, lang, size)
            try:
                res = ES.search(index=ES_INDEX, body=body, params={"error_trace": "true"})
            except BadRequestError as e:
                print("ES BadRequestError (fallback):", getattr(e, "info", e)); raise
            hits = res.get("hits", {}).get("hits", [])

        # === parse ===
        out_hits = []
        for h in hits:
            src = h.get("_source", {}) or {}
            evid_blocks = src.get("multidim_event_json", []) or []

            raw_content = ((src.get("rawInfo") or {}).get("content") or "").strip()
            article_date_iso = _parse_article_date_iso(raw_content)
            tl_dates = _collect_timeline_dates(src)

            citations = []
            if isinstance(evid_blocks, list):
                for block in evid_blocks:
                    for snip in (block or {}).get("evidence_snippets", []) or []:
                        item = {
                            "text": snip.get("text"),
                            "source_id": snip.get("source_id"),
                            "paragraph_id": snip.get("paragraph_id"),
                        }
                        di = _infer_date_for_snippet(item["text"] or "", article_date_iso, tl_dates)
                        if di: item["date_iso"] = di
                        citations.append(item)

            hl = (h.get("highlight", {}) or {}).get("rawInfo.content", []) or []
            if not citations and hl:
                for frag in hl:
                    item = {"text": frag, "source_id": None}
                    di = _infer_date_for_snippet(frag or "", article_date_iso, tl_dates)
                    if di: item["date_iso"] = di
                    citations.append(item)

            date_span = None
            if tl_dates:
                try: date_span = {"min": min(tl_dates), "max": max(tl_dates)}
                except Exception: pass

            out_hits.append({
                "uuid": src.get("uuid"),
                "subject": (src.get("communication", {}) or {}).get("subject"),
                "score": h.get("_score"),
                "citations": citations[:5],
                "article_date_iso": article_date_iso,
                "event_dates": tl_dates[:20],
                "event_date_span": date_span,
            })

        return {"hits": out_hits}

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
            "description": "最多回傳多少筆時間線事件（1–50；預設 10）",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
            "nullable": True
        },
    }
    output_type = "string"

    def forward(self, uuid: Optional[str] = None, k: Optional[int] = 10):
        if not uuid:
            return {"timeline": [], "error": "uuid is required"}
        try:
            res = ES.search(
                index=ES_INDEX,
                body={"size": 1, "query": {"term": {"uuid.keyword": uuid}},
                      "_source": ["multidim_event_json.Event_Timeline"]},
                params={"error_trace": "true"},
            )
        except BadRequestError as e:
            print("ES BadRequestError (timeline):", getattr(e, "info", e)); raise

        items: List[Dict[str, Any]] = []
        hit = (res.get("hits", {}) or {}).get("hits", [])
        if hit:
            blocks = (hit[0].get("_source", {}) or {}).get("multidim_event_json", []) or []
            for b in blocks:
                for t in (b or {}).get("Event_Timeline", []) or []:
                    items.append({"date_iso": t.get("date_iso"),
                                  "date_raw": t.get("date_raw"),
                                  "description": t.get("description")})
        items = [i for i in items if i.get("date_iso")]
        items.sort(key=lambda x: x["date_iso"])
        return {"timeline": items[: (k or 10)]}
