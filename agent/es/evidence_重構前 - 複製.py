# agent/es/evidence.py
import json
import re
import os
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ====== 小工具：處理 multidim_event_json ======

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

        
# ===== 簡易日期工具（原樣保留） =====
_YMD = re.compile(r'(?P<y>20\d{2}|19\d{2})[年/\-\.](?P<m>\d{1,2})[月/\-\.](?P<d>\d{1,2})日?')
_MD  = re.compile(r'(?P<m>\d{1,2})月(?P<d>\d{1,2})日')
_TODAY_D = re.compile(r'今[（(](?P<d>\d{1,2})[）)]日')
_PAREN_D = re.compile(r'[（(](?P<d>\d{1,2})日[）)]')

def _norm_date(y: int, m: int, d: int) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


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

def _infer_date_for_snippet(text: str, article_date_iso: str | None, timeline_dates: list[str]) -> str | None:
    if not text: return None
    # 1) 直接看 snippet 裡有沒有「yyyy年m月d日」
    m = _YMD.search(text)
    if m: return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))
    art_y = art_m = None
    if article_date_iso and len(article_date_iso) >= 10:
        art_y = int(article_date_iso[0:4]); art_m = int(article_date_iso[5:7])
    tl_years = sorted({int(di[0:4]) for di in timeline_dates if len(di) >= 10})
    
    # 2) 「x月y日」→ 帶上文章年份或 timeline 唯一年份
    m = _MD.search(text)
    if m:
        mm, dd = int(m.group('m')), int(m.group('d'))
        year = art_y or (tl_years[0] if len(tl_years) == 1 else None)
        if year: return _norm_date(year, mm, dd)
    
    # 3) 「今(12)日」、「(12日)」→
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

# 日期清洗（避免 0125/1992 這類超出分析範圍的雜訊）——
def _is_valid_year(di: str) -> bool:
    try:
        y = int(di[:4])
        return 1900 <= y <= 2100
    except Exception:
        return False
    
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

def _normalize_for_match(s: str) -> str:
    """
    用來做主題詞比對的輕量正規化：
    - NFKC：統一全形/半形
    - lower()：英文大小寫忽略
    - 統一各種破折號、短橫為 '-'
    - 把所有空白拿掉（含全形空白）
    """
    _PUNCT = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = re.sub(r"[‐-–—−]", "-", s)
    s = re.sub(r"\s+", "", s)
    s = _PUNCT.sub("", s)   # ★ 新增：去掉標點/括號/斜線/點號等
    return s

def _match_topic(
    ev_text: str,
    subject: Optional[str],
    title: Optional[str],
    term_groups: List[Set[str]],
    *,
    min_groups_required: Optional[int] = None,   # ★ 新增
) -> Tuple[bool, Set[str], str, int]:
    """
    語意群組版主題詞過濾：

    - term_groups: list[set[str]]，每一組是一個語意軸（例如「敘利亞」群、「化學武器」群）
    - 若 term_groups 為空 → 不過濾（避免誤殺其他任務）

    判斷邏輯（嚴格）：
    - 1 軸：命中 1 軸即可
    - 2 軸：兩軸都要命中
    - 3 軸：三軸都要命中
    - 4 軸以上：至少命中 3 軸
    
    寬鬆：
    命中　min_groups_required 數量即可
    """
    if not term_groups:
        return True, set(), "no_filter", 0

    #haystack_raw = (ev_text or "") + " " + (subject or "") + " " + (title or "")
    #haystack_norm = _normalize_for_match(haystack_raw)
    text_norm = _normalize_for_match(ev_text or "")
    subj_norm = _normalize_for_match(subject or "")
    title_norm = _normalize_for_match(title or "")
    
    hit_terms: set[str] = set()
    group_hits = 0
    hit_in_text = False
    hit_in_meta = False

    for g in term_groups:
        if not g:
            continue

        g_hit: set[str] = set()
        for t in g:
            if not t:
                continue
            t_norm = _normalize_for_match(t)
            #if t_norm and t_norm in haystack_norm:
            #    g_hit.add(t)
            if not t_norm:
                continue
            
            in_text = t_norm in text_norm
            in_meta = (t_norm in subj_norm) or (t_norm in title_norm)
            
            if in_text or in_meta:
                g_hit.add(t)
                if in_text:
                    hit_in_text = True
                if in_meta:
                    hit_in_meta = True

        if g_hit:
            group_hits += 1
            hit_terms |= g_hit

    if group_hits == 0:
        return False, set(), "none", 0

    if hit_in_text and hit_in_meta:
        scope = "mixed"
    elif hit_in_text:
        scope = "text"
    elif hit_in_meta:
        scope = "meta"
    else:
        scope = "none"
        
    # ★ 若指定 min_groups_required：直接用門檻
    if min_groups_required is not None:
        #return (group_hits >= min_groups_required), hit_terms
        return (group_hits >= min_groups_required), hit_terms, scope, group_hits
    
    num_groups = len(term_groups)

    # 單一語意軸：命中至少一組就可
    if num_groups <= 1:
        #return True, hit_terms
        return True, hit_terms, scope, group_hits

    # 兩軸：全部都要命中（等於 AND）
    if num_groups == 2:
        return (group_hits == 2), hit_terms, scope, group_hits

    # 三軸：全部都要命中，避免「只中敘利亞+化武」卻沒「調查」也通過
    if num_groups == 3:
        return (group_hits == 3), hit_terms, scope, group_hits

    # 四軸以上：至少命中 3 軸，避免太嚴格直接篩成 0
    if group_hits >= 3:
        return True, hit_terms, scope, group_hits

    return False, hit_terms, scope, group_hits

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


# ====== 高階 API：ES hits → filtered_hits + evidence_snippets ======

def build_hits_and_evidence(
    es_hits: List[Dict[str, Any]],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    effective_terms: Optional[List[str]],
    term_groups: List[Set[str]],
    query_for_snippet: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """
    把 ES raw hits 轉成：
    - filtered_hits: 只保留至少有一段 evidence_snippet 的文件
    - evidence_snippets: 已處理好日期 / 主題詞 / fallback 的片段
    - syn_snippets_count: 其中有 synonym_hits 的片段數量（給 log 用）
    """
    def _collect_snippets(min_groups_required: Optional[int] = None) -> List[Dict[str, Any]]:
        snaps: List[Dict[str, Any]] = []
        for h in out_hits:
            h_subject = h.get("subject")
            h_title = h.get("article_title")
            for c in h.get("citations") or []:
                ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                if ev is None:
                    continue
    
                # ★ 錨點
                #haystack_raw = (ev["text"] or "") + " " + (h_subject or "") + " " + (h_title or "")
                #haystack_norm = _normalize_for_match(haystack_raw)
                #if core_terms and not _hit_any_terms(haystack_norm, core_terms):
                #    continue
                '''
                ok, hit_terms = _match_topic(ev["text"], h_subject, h_title, term_groups,
                                             min_groups_required=min_groups_required)
                if not ok:
                    continue
    
                if hit_terms:
                    ev["synonym_hits"] = list(hit_terms)
                ev["match_policy"] = "relaxed" if min_groups_required is not None else "strict"
                snaps.append(ev)
                '''
                ok, hit_terms, scope, gh = _match_topic(
                    ev["text"], h_subject, h_title, term_groups,
                    min_groups_required=min_groups_required
                )
                if not ok:
                    continue
                
                # 命中詞
                if hit_terms:
                    ev["synonym_hits"] = list(hit_terms)
                
                # 命中範圍（text / meta / mixed）
                ev["match_scope"] = scope
                ev["group_hits"] = gh  # 可選，但很常用來 debug
                
                # ✅ 只靠 subject/title 命中 → 標記 weak
                if scope == "meta":
                    ev["weak_evidence"] = True
                
                ev["match_policy"] = "relaxed" if min_groups_required is not None else "strict"
                snaps.append(ev)
        return snaps
    
    out_hits: List[Dict[str, Any]] = []

    # ===== 統計用（避免 log 太吵）=====
    n_es_hits = len(es_hits or [])
    n_inner_used = 0
    n_fallback_used = 0
    n_total_citations = 0
    
    # 1) 先把 ES hit 整理成 out_hits（帶 citations / timeline / article_date_iso）
    for h in es_hits:
        src = h.get("_source", {}) or {}

        citations = []
        ih = (h.get("inner_hits") or {}).get("evi") or {}
        ih_hits = (ih.get("hits") or {}).get("hits") or []
        if ih_hits:
            #n_inner_used += 1
            for eh in ih_hits[:3]:
                esrc = (eh.get("_source") or {})
                txt = esrc.get("text")
                sid = esrc.get("source_id")
                pid = esrc.get("paragraph_id")
                if not txt:
                    nested = (
                        esrc.get("multidim_event_json", {})
                        .get("evidence_snippets", {})
                    )
                    txt = nested.get("text")
                    sid = nested.get("source_id")
                    pid = nested.get("paragraph_id")
                if txt:
                    citations.append(
                        {"text": txt, "source_id": sid, "paragraph_id": pid}
                    )
            if citations:
                n_inner_used += 1

        raw_content = ((src.get("rawInfo") or {}).get("content") or "").strip()

        # 沒 inner_hits 時，用關鍵字窗格自己切一段
        if not citations:
            snippet = _make_fallback_snippet(raw_content, query_for_snippet or "", width=180)
            if snippet:
                n_fallback_used += 1
                citations.append(
                    {"text": snippet, "source_id": None, "paragraph_id": None}
                )
        
        n_total_citations += len(citations)
        
        article_date_iso = _parse_article_date_iso(raw_content)
        tl_dates = _collect_timeline_dates(src)

        if (not article_date_iso) and tl_dates:
            article_date_iso = tl_dates[0]

        subject = (src.get("communication", {}) or {}).get("subject")
        article_title = (src.get("multidim_event_json") or {}).get("article_title")

        for c in citations:
            di = _infer_date_for_snippet(c.get("text") or "", article_date_iso, tl_dates)
            if di:
                c["date_iso"] = di
            c["uuid"] = src.get("uuid")
            if subject:
                c["subject"] = subject

        # 清掉不合理年份
        for c in citations:
            di = c.get("date_iso")
            if di and not _is_valid_year(di):
                c.pop("date_iso", None)

        out_hits.append(
            {
                "uuid": src.get("uuid"),
                "subject": subject,
                "score": h.get("_score"),
                "citations": citations[:8],
                "article_date_iso": article_date_iso,
                "event_dates": tl_dates[:20],
                "event_date_span": {
                    "min": min(tl_dates),
                    "max": max(tl_dates),
                }
                if tl_dates
                else None,
                "article_title": article_title,
                "selectedMessage": src.get("selectedMessage"),
                "highValue": (
                    ((src.get("ai") or {}).get("classLabels") or {}).get("highValue")
                ),
            }
        )

    # ✅ 重要：先 log 一次「輸入→整理後」概況（短、好查）
    logger.info(
        "build_hits_and_evidence: es_hits=%d out_hits=%d citations=%d inner_used=%d fallback_used=%d "
        "term_groups=%d effective_terms=%d date_range=%s~%s",
        n_es_hits, len(out_hits), n_total_citations, n_inner_used, n_fallback_used,
        len(term_groups or []), len(effective_terms or []),
        date_from or "N/A", date_to or "N/A",
    )
    
    # 2) 組 evidence_snippets（主題詞過濾 + 日期過濾）
    term_groups = term_groups or []


    # 先嚴格
    evidence_snippets = _collect_snippets(min_groups_required=None)
    logger.info("build_hits_and_evidence: evidence strict=%d", len(evidence_snippets))

    # ✅ 逐步放寬：strict -> (strict_req-1 ... 1)
    if not evidence_snippets and out_hits and term_groups:
        n = len(term_groups)
        strict_req = 1 if n <= 1 else (2 if n == 2 else (3 if n == 3 else 3))
    
        # 例如 n=3: 先試 2，再試 1
        for req in range(strict_req - 1, 0, -1):
            logger.warning(
                "build_hits_and_evidence: strict evidence=0 -> relax try (groups=%d strict_req=%d try_req=%d)",
                n, strict_req, req
            )
            tmp = _collect_snippets(min_groups_required=req)
            logger.info("build_hits_and_evidence: evidence relaxed(req=%d)=%d", req, len(tmp))
            if tmp:
                evidence_snippets = tmp
                break
            
    # 3) fallback：沒有主題詞時，避免被全部過濾掉
    if not evidence_snippets and out_hits and not (effective_terms or []):
        logger.warning("build_hits_and_evidence: evidence=0 and no effective_terms -> fallback pick first citation")
        for h in out_hits[:10000]:
            for c in (h.get("citations") or [])[:1]:
                ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                if ev is None:
                    continue
                evidence_snippets.append(ev)
        logger.info("build_hits_and_evidence: evidence fallback(no_terms)=%d", len(evidence_snippets))


    # 4) fallback：有主題詞但沒 snippet → 用「包含任一 effective_term」的寬鬆條件
    if not evidence_snippets and out_hits and (effective_terms or []):
        logger.warning("build_hits_and_evidence: evidence=0 with effective_terms -> fallback contains-any-effective-term")
        new_snippets: List[Dict[str, Any]] = []
        eff = [t for t in (effective_terms or []) if t]
        for h in out_hits:
            h_subject = h.get("subject")
            h_title = h.get("article_title")

            for c in h.get("citations") or []:
                ev = _build_ev_from_hit_and_citation(h, c, date_from, date_to)
                if ev is None:
                    continue

                text = ev["text"]
                #haystack = (text or "") + " " + (h_subject or "") + " " + (h_title or "")
                #hit_terms = {t for t in eff if t and t in haystack}
                haystack_norm = _normalize_for_match((text or "") + " " + (h_subject or "") + " " + (h_title or ""))
                hit_terms = {t for t in eff if t and _normalize_for_match(t) in haystack_norm}
                ev["match_scope"] = "fallback_any_term"
                ev["weak_evidence"] = True  # 這條 fallback 本來就寬，通常視為弱證據
                if not hit_terms:
                    continue
                ev["synonym_hits"] = list(hit_terms)
                new_snippets.append(ev)
        if new_snippets:
            evidence_snippets = new_snippets
        logger.info("build_hits_and_evidence: evidence fallback(effective_terms)=%d", len(evidence_snippets))

    # 5) 只保留「至少有一段 evidence_snippet」的文件
    if evidence_snippets:
        kept_uuids = {ev["uuid"] for ev in evidence_snippets if ev.get("uuid")}
        filtered_hits = [h for h in out_hits if h.get("uuid") in kept_uuids]
    else:
        filtered_hits = out_hits

    syn_snippets = sum(1 for ev in evidence_snippets if ev.get("synonym_hits"))
    weak_cnt = sum(1 for ev in evidence_snippets if ev.get("weak_evidence"))
    
    # ✅ 收尾總結：一行看懂產出
    logger.info(
        "build_hits_and_evidence: filtered_hits=%d evidence=%d syn_snippets=%d weak=%d",
        len(filtered_hits), len(evidence_snippets), syn_snippets, weak_cnt
    )
    
    return filtered_hits, evidence_snippets, syn_snippets