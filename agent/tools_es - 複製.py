# agent/tools_es.py
import os
import re
from typing import Optional, List, Dict, Any
from elasticsearch import Elasticsearch
from smolagents import Tool

# === 日期解析與補全 ===
_YMD = re.compile(r'(?P<y>20\d{2}|19\d{2})[年/\-\.](?P<m>\d{1,2})[月/\-\.](?P<d>\d{1,2})日?')
_MD  = re.compile(r'(?P<m>\d{1,2})月(?P<d>\d{1,2})日')
_TODAY_D = re.compile(r'今[（(](?P<d>\d{1,2})[）)]日')       # 今（29）日
_PAREN_D = re.compile(r'[（(](?P<d>\d{1,2})日[）)]')        # （29日）

def _norm_date(y: int, m: int, d: int) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

def _parse_article_date_iso(raw: str) -> str | None:
    """從全文第一個 YYYY年M月D日 擷取主日期（新聞常見抬頭/內文前段）。"""
    if not raw: 
        return None
    m = _YMD.search(raw)
    if not m:
        return None
    return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

def _collect_timeline_dates(src: dict) -> list[str]:
    """收集 Event_Timeline 裡的 date_iso（去重、有序）。"""
    uniq = []
    seen = set()
    for blk in (src.get("multidim_event_json") or []):
        for t in (blk or {}).get("Event_Timeline") or []:
            di = t.get("date_iso")
            if di and di not in seen:
                seen.add(di)
                uniq.append(di)
    return uniq

def _infer_date_for_snippet(text: str, article_date_iso: str | None, timeline_dates: list[str]) -> str | None:
    """
    從 snippet 裡的文字補全完整日期：
    優先順序：
    1) 直接有 YYYY-M-D → 回傳
    2) 只有 M月D日 → 用文章年（article_date_iso）或 timeline 年（唯一時）補年
    3) 今（D）日 / （D日） → 優先用 article 的年/月 搭配 D；否則從 timeline 找 day 相符者；再不行回 None
    """
    if not text:
        return None

    # 1) 直接有完整 YMD
    m = _YMD.search(text)
    if m:
        return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

    # 準備候選年/月
    art_y = art_m = None
    if article_date_iso and len(article_date_iso) >= 10:
        art_y = int(article_date_iso[0:4])
        art_m = int(article_date_iso[5:7])

    tl_years = sorted({int(di[0:4]) for di in timeline_dates if len(di) >= 10})
    tl_months = sorted({int(di[5:7]) for di in timeline_dates if len(di) >= 10})

    # 2) M月D日（補年）
    m = _MD.search(text)
    if m:
        mm, dd = int(m.group('m')), int(m.group('d'))
        year = art_y or (tl_years[0] if len(tl_years) == 1 else None)
        if year:
            return _norm_date(year, mm, dd)

    # 3) 今（D）日 or （D日）→ 先用 article 的年/月；不行再從 timeline 找 day 相符
    m = _TODAY_D.search(text) or _PAREN_D.search(text)
    if m:
        dd = int(m.group('d'))
        # a) 文章有年月 → 直接補
        if art_y and art_m:
            return _norm_date(art_y, art_m, dd)
        # b) 從 timeline 裡找 day 相符者（優先最接近的）
        for di in timeline_dates:
            try:
                y, mm, d = int(di[0:4]), int(di[5:7]), int(di[8:10])
                if d == dd:
                    return _norm_date(y, mm, d)
            except Exception:
                continue

    return None

# ===== ES 連線 =====
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = os.getenv("ES_INDEX", "news_test")
ES = Elasticsearch(ES_URL)


RUNTIME_MAPPINGS = {
    "subject_rt": {
        "type": "keyword",
        "script": {"source": """
          def c = params._source['communication'];
          if (c != null) { def s = c['subject']; if (s != null) emit(s); }
        """}
    },
    "content_rt": {
        "type": "keyword",
        "script": {"source": """
          def r = params._source['rawInfo'];
          if (r != null) { def t = r['content']; if (t != null) emit(t); }
        """}
    },

    # ★ 改成輸出 epoch millis
    "event_dt_rt": {
      "type": "date",
      "format": "yyyy-MM-dd||yyyy-MM||yyyy",
      "script": {
        "source": """
          def blocks = params._source['multidim_event_json'];
          if (blocks == null) return;
          def blocksArr = (blocks instanceof List) ? blocks : [blocks];
    
          int count = 0;  // ← 計數器
    
          for (def b : blocksArr) {
            if (b == null) continue;
            def tl = b['Event_Timeline'];
            if (tl == null) continue;
            def tlArr = (tl instanceof List) ? tl : [tl];
    
            for (def t : tlArr) {
              if (t == null) continue;
              def d = t['date_iso'];
              if (d == null) continue;
    
              String x = d.toString().trim();
              if (x.length() == 0) continue;
    
              x = x.replace('/', '-').replace('／', '-').replace('.', '-')
                   .replace('年', '-').replace('月', '-').replace('日', '');
    
              if (x.length() < 4) continue;
              String yy = x.substring(0, 4);
    
              boolean okYear = true;
              for (int i = 0; i < 4; i++) {
                int cp = yy.codePointAt(i);
                if (cp < 48 || cp > 57) { okYear = false; break; }
              }
              if (!okYear) continue;
    
              String mm = null;
              String dd = null;
              int p1 = x.indexOf('-');
              if (p1 > 0) {
                int p2 = x.indexOf('-', p1 + 1);
                if (p2 > 0) { mm = x.substring(p1 + 1, p2); dd = x.substring(p2 + 1); }
                else        { mm = x.substring(p1 + 1); }
              }
              if (mm != null && mm.length() == 1) mm = '0' + mm;
              if (dd != null && dd.length() == 1) dd = '0' + dd;
    
              int y  = Integer.parseInt(yy);
              int mo = (mm != null && mm.length() > 0) ? Integer.parseInt(mm) : 1;
              int da = (dd != null && dd.length() > 0) ? Integer.parseInt(dd) : 1;
    
              def zdt = java.time.ZonedDateTime.of(y, mo, da, 0, 0, 0, 0, java.time.ZoneId.of("UTC"));
              emit(zdt.toInstant().toEpochMilli());
    
              // ★ 超過 100 就停
              count++;
              if (count >= 100) return;
            }
          }
        """
      }
    },

    "event_year_rt": {
      "type": "keyword",
      "script": {
        "source": """
          def blocks = params._source['multidim_event_json'];
          if (blocks == null) return;
          def blocksArr = (blocks instanceof List) ? blocks : [blocks];
    
          def years = new java.util.HashSet();  // ← 去重
          for (def b : blocksArr) {
            if (b == null) continue;
            def tl = b['Event_Timeline'];
            if (tl == null) continue;
            def tlArr = (tl instanceof List) ? tl : [tl];
    
            for (def t : tlArr) {
              if (t == null) continue;
              def d = t['date_iso'];
              if (d == null) continue;
    
              String s = d.toString();
              if (s.length() < 4) continue;
              String y = s.substring(0, 4);
    
              boolean ok = true;
              for (int i = 0; i < 4; i++) {
                int cp = y.codePointAt(i);
                if (cp < 48 || cp > 57) { ok = false; break; }
              }
              if (!ok) continue;
    
              years.add(y);
              if (years.size() >= 100) break;   // ★ 上限
            }
            if (years.size() >= 100) break;
          }
    
          for (def y : years) emit(y);
        """
      }
    }
}

# ===== Tool 1：混合檢索（BM25 + 過濾 + 空結果 fallback） =====
class ESSearchNews(Tool):
    name = "es_search_news"
    description = (
        "在指定索引以 BM25 搜索重點段落，支援 highValue / lang / date 過濾；"
        "回傳命中文本片段（evidence 或 highlight）、uuid、subject、分數。"
    )
    inputs = {
        "query": {"type": "string", "description": "使用者查詢關鍵字", "nullable": True},
        "must_high_value": {
            "type": "boolean",
            "description": "僅取 ai.classLabels.highValue=true 的文件",
            "default": True,
            "nullable": True,
        },
        "lang": {  # ← 保留，但忽略
            "type": "string",
            "description": "（已忽略）語言過濾關閉",
            "default": None,
            "nullable": True,
        },
        "size": {
            "type": "integer",
            "description": "返回筆數上限",
            "default": 5, "minimum": 1, "maximum": 20, "nullable": True,
        },
        "date_from": {"type": "string", "description": "ISO 起始時間（filter 事件日期 event_dt_rt）", "nullable": True},
        "date_to":   {"type": "string", "description": "ISO 結束時間（filter 事件日期 event_dt_rt）", "nullable": True},
    }
    output_type = "string"  # smolagents 會把 dict 序列化成字串
    def _extract_topic_terms(self,q: str) -> List[str]:
        s = (q or "")
        terms = set()
        # 同義詞：拉拉隊 / 啦啦隊
        #if "拉拉隊" in s or "啦啦隊" in s:
            #terms.update(["拉拉隊", "啦啦隊"])
        # 抓所有連續中⽂（>=2）當備用
        for m in re.findall(r'[\u4e00-\u9fff]{2,}', s):
            terms.add(m)
        # 移除常見虛詞
        stop = {"請整理", "相關", "重點", "事件", "年", "月份", "月", "日"}
        terms = [t for t in terms if t not in stop]
        # 若抓不到，就回空（不加強制）
        return list(dict.fromkeys(terms))


    def _build_query_body(
        self,
        query: Optional[str],
        must_high_value: Optional[bool],
        lang: Optional[str],            # ← 參數保留但不使用
        size: Optional[int],
        date_from: Optional[str],
        date_to: Optional[str],
        with_date: bool = True,
    ) -> Dict[str, Any]:
        
    
        # ====== filters：只用事件時間，不用 importDT ======
        filters: List[Dict[str, Any]] = []
        if must_high_value:
            filters.append({"term": {"ai.classLabels.highValue": True}})
        
        q = (query or "").strip()
        
        
        topic_terms = self._extract_topic_terms(q)
        
        topic_must = []
        if topic_terms:
            topic_should = []
            for kw in topic_terms:
                # 用 runtime keyword 欄位做子字串比對（避免 text 欄位 wildcard 效能/語法問題）
                topic_should.append({"wildcard": {"subject_rt": {"value": f"*{kw}*"}}})
                topic_should.append({"wildcard": {"content_rt": {"value": f"*{kw}*"}}})
            topic_must.append({"bool": {"should": topic_should, "minimum_should_match": 1}})
            
        m = re.search(r'(?:19|20)\d{2}', q)
        year_in_query = m.group(0) if m else None
        
        # 指定 date_from/date_to → 針對事件日期做 range
        if with_date and (date_from or date_to):
            rng = {"range": {"event_dt_rt": {}}}
            if date_from:
                rng["range"]["event_dt_rt"]["gte"] = date_from
            if date_to:
                rng["range"]["event_dt_rt"]["lte"] = date_to
            filters.append(rng)
        
        years = re.findall(r'(?:19|20)\\d{2}', q)
        years = list(dict.fromkeys(years))  # 去重並保持順序
        if with_date and years and not (date_from or date_to):
            filters.append({"terms": {"event_year_rt": years}})
    
        should_clauses: List[Dict[str, Any]] = []
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
    
        subject_kw = "communication.subject.keyword"
        def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
    
        if q:
            should_clauses.append(wc("communication.subject", f"*{q}*"))
            should_clauses.append(wc("rawInfo.content",     f"*{q}*"))
            should_clauses.append(wc(subject_kw,            f"*{q}*"))
    
        tax_shoulds, tariff_shoulds = [], []
    
        #if "免稅" in q or "所得稅" in q or "月薪" in q:
        #    for pat in ["*免*稅*", "*免繳*所得稅*", "*月薪*5*萬*"]:
        #        tax_shoulds += [wc(subject_kw, pat), wc("communication.subject", pat), wc("rawInfo.content", pat)]
    
        #if ("家具" in q and "關稅" in q) or ("家具關稅" in q):
        #    tariff_shoulds += [
        #        {"bool": {"must": [wc(subject_kw, "*家具*"), wc(subject_kw, "*關稅*")]}},
        #        {"bool": {"must": [wc("communication.subject", "*家具*"), wc("communication.subject", "*關稅*")]}},
        #        {"bool": {"must": [wc("rawInfo.content", "*家具*"), wc("rawInfo.content", "*關稅*")]}},
        #    ]
        should_clauses += tax_shoulds + tariff_shoulds

        must_clauses = []
        if year_in_query:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"wildcard": {"subject_rt": {"value": f"*{year_in_query}*"}}},
                        {"wildcard": {"content_rt": {"value": f"*{year_in_query}*"}}},
                        {"wildcard": {"communication.subject": {"value": f"*{year_in_query}*"}}},
                        {"wildcard": {"rawInfo.content": {"value": f"*{year_in_query}*"}}},
                    ],
                    "minimum_should_match": 1
                }
            })    
        body = {
            "size": size or 5,
            "track_total_hits": True,
            "_source": [
                "uuid",
                "communication.subject",
                "rawInfo.content",
                "multidim_event_json.evidence_snippets",
                "multidim_event_json.article_title",
                "multidim_event_json.Event_Timeline"  # ← 新增：取回日期
            ],
            "runtime_mappings": RUNTIME_MAPPINGS,
            "query": {
                "bool": {
                    "must": topic_must,
                    "should": should_clauses + [
                        {"wildcard": {"subject_rt": {"value": f"*{q}*"}}},
                        {"wildcard": {"content_rt": {"value": f"*{q}*"}}},
                        #{"wildcard": {"subject_rt": {"value": "*免*稅*"}}},
                        #{"wildcard": {"subject_rt": {"value": "*免*繳*所*得*稅*"}}},
                        #{"wildcard": {"subject_rt": {"value": "*月薪*5*萬*"}}},
                        #{"wildcard": {"content_rt": {"value": "*免*稅*"}}},
                        #{"wildcard": {"content_rt": {"value": "*免*繳*所*得*稅*"}}},
                        #{"wildcard": {"content_rt": {"value": "*月薪*5*萬*"}}},
                        #{"bool": {"must": [
                        #    {"wildcard": {"subject_rt": {"value": "*家具*"}}},
                        #    {"wildcard": {"subject_rt": {"value": "*關稅*"}}}
                        #]}},
                        #{"bool": {"must": [
                        #    {"wildcard": {"content_rt": {"value": "*家具*"}}},
                        #    {"wildcard": {"content_rt": {"value": "*關稅*"}}}
                        #]}},
                    ],
                    "minimum_should_match": 1,
                    "filter": filters,
                    # ★ 新增：若 query 有年份，則年份必須出現於文字中
                    #（真的要保留也行，但很容易誤殺；建議先移除，僅用事件年份過濾。）
                    #"must": must_clauses
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
        #print("~"*50); print("body in _build_query_body", body); print("~"*50)
        return body

    def _build_script_fallback_body(
        self,
        query: str,
        must_high_value: Optional[bool],
        lang: Optional[str],      # ← 參數保留但不使用
        size: Optional[int],
    ) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if must_high_value:
            filters.append({"term": {"ai.classLabels.highValue": True}})
        # ← 不再加入語言條件
        q_year = None
        m = re.search(r'(?:19|20)\d{2}', query or "")
        if m:
            q_year = m.group(0)    
        topic_terms = self._extract_topic_terms(query or "")
        body = {
            "size": size or 5,
            "_source": [
              "uuid",
              "communication.subject",
              "rawInfo.content",
              "multidim_event_json.evidence_snippets",
              "multidim_event_json.article_title"
            ],
            "runtime_mappings": RUNTIME_MAPPINGS,
            "query": {
                "script": {
                  "script": {
                    "lang": "painless",
                    "params": {"q": query, "year": q_year, "must_any": topic_terms},
                    "source": """
                      String s = (doc.containsKey('subject_rt') && !doc['subject_rt'].empty)
                                 ? doc['subject_rt'].value : null;
                      String c = (doc.containsKey('content_rt') && !doc['content_rt'].empty)
                                 ? doc['content_rt'].value : null;
            
                      // 年份過濾（如有）
                      if (params.year != null) {
                        boolean ok = false;
                        if (doc.containsKey('event_year_rt')) {
                          def ys = doc['event_year_rt'];
                          for (int i=0; i<ys.size(); i++) {
                            if (ys.get(i).value.equals(params.year)) { ok = true; break; }
                          }
                        }
                        if (!ok) return false;
                      }
            
                      // 主題詞至少命中一個
                      if (params.must_any != null && params.must_any.size() > 0) {
                        boolean topicOk = false;
                        for (int i=0; i<params.must_any.size(); i++) {
                          def kw = params.must_any.get(i);
                          if ((s != null && s.contains(kw)) || (c != null && c.contains(kw))) { topicOk = true; break; }
                        }
                        if (!topicOk) return false;
                      }
            
                      // 放寬：只要含部分 query 片段或本身包含主題詞就算（fallback 才用）
                      return true;
                    """
              }
            }
          }
        }
    
        if filters:
            body["query"] = {"bool": {"must": [body["query"]], "filter": filters}}
    
        return body

    def forward(
        self,
        query: Optional[str] = None,
        must_high_value: Optional[bool] = True,
        lang: Optional[str] = "C",
        size: Optional[int] = 5,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ):
        if not query:
            return {"hits": [], "error": "query is required"}
    
        # 1) 有日期
        body = self._build_query_body(query, must_high_value, lang, size, date_from, date_to, with_date=True)
        res = ES.search(index=ES_INDEX, body=body)
        hits = res.get("hits", {}).get("hits", [])
    
        # 2) 拿掉日期
        if not hits and (date_from or date_to):
            body = self._build_query_body(query, must_high_value, lang, size, None, None, with_date=False)
            res = ES.search(index=ES_INDEX, body=body)
            hits = res.get("hits", {}).get("hits", [])
    
        # 3) 仍 0 筆 → 用與你最小測試一樣的「頂層 script」fallback
        if not hits:
            print(">>>>>>>> [FALLBACK] using script query at top-level")
            body = self._build_script_fallback_body(query, must_high_value, lang, size)
            res = ES.search(index=ES_INDEX, body=body)
            hits = res.get("hits", {}).get("hits", [])
    
        # === parse（同你原本） ===
        out_hits = []
        for h in hits:
            src = h.get("_source", {}) or {}
            evid_blocks = src.get("multidim_event_json", []) or []
            
            # 文章原文（用來抓主日期）
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
                        # ★ 核心：為 snippet 推斷完整日期
                        di = _infer_date_for_snippet(item["text"] or "", article_date_iso, tl_dates)
                        if di:
                            item["date_iso"] = di
                        citations.append(item)
                        
            hl = (h.get("highlight", {}) or {}).get("rawInfo.content", []) or []
            if not citations and hl:
                for frag in hl:
                    item = {"text": frag, "source_id": None}
                    di = _infer_date_for_snippet(frag or "", article_date_iso, tl_dates)
                    if di:
                        item["date_iso"] = di
                    citations.append(item)
        
            # 整理 timeline 的最小/最大日期（可給 LLM 當上下文）
            date_span = None
            if tl_dates:
                try:
                    date_span = {"min": min(tl_dates), "max": max(tl_dates)}
                except Exception:
                    pass
        
            out_hits.append({
                "uuid": src.get("uuid"),
                "subject": (src.get("communication", {}) or {}).get("subject"),
                "score": h.get("_score"),
                "citations": citations[:5],
                # ★ 對代理人與前端都很有用的上下文
                "article_date_iso": article_date_iso,
                "event_dates": tl_dates[:20],      # 適度截斷，避免 payload 太大
                "event_date_span": date_span,
            })
        return {"hits": out_hits}


# ===== Tool 2：事件時間線 =====
class ESTimeline(Tool):
    name = "es_timeline"
    description = "讀取指定 uuid 的 multidim_event_json.Event_Timeline，回傳依日期排序的 {date_iso, date_raw, description}"
    inputs = {
        "uuid": {
            "type": "string",
            "description": "指定文件的 uuid",
            "nullable": True,  # ← 和簽名一致（Optional[str] = None）
        },
        "k": {
            "type": "integer",
            "description": "最多回傳多少筆",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
            "nullable": True,  # ← 和簽名一致（Optional[int] = 10）
        },
    }
    output_type = "string"

    def forward(self, uuid: Optional[str] = None, k: Optional[int] = 10):
        if not uuid:
            return {"timeline": [], "error": "uuid is required"}

        res = ES.search(
            index=ES_INDEX,
            body={
                "size": 1,
                "query": {"term": {"uuid.keyword": uuid}},
                "_source": ["multidim_event_json.Event_Timeline"],
            },
        )
        items: List[Dict[str, Any]] = []
        hit = (res.get("hits", {}) or {}).get("hits", [])
        if hit:
            blocks = (hit[0].get("_source", {}) or {}).get("multidim_event_json", []) or []
            for b in blocks:
                for t in (b or {}).get("Event_Timeline", []) or []:
                    items.append(
                        {
                            "date_iso": t.get("date_iso"),
                            "date_raw": t.get("date_raw"),
                            "description": t.get("description"),
                        }
                    )

        # 排序 & 取前 k
        items = [i for i in items if i.get("date_iso")]
        items.sort(key=lambda x: x["date_iso"])
        return {"timeline": items[: (k or 10)]}
