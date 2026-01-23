# agent/es/evidence.py
from __future__ import annotations

import json
import re
import unicodedata
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Iterable

logger = logging.getLogger(__name__)


# =========================
# Models / Config
# =========================

@dataclass(frozen=True)
class EvidenceBuildConfig:
    inner_hit_topk: int = 3
    citations_per_doc: int = 8
    fallback_width: int = 180
    max_docs_for_fallback: int = 10000
    timeline_dates_topk: int = 20

@dataclass
class Citation:
    text: str
    source_id: Optional[str] = None
    paragraph_id: Optional[str] = None
    date_iso: Optional[str] = None  # snippet 推斷日期（若有）
    uuid: Optional[str] = None
    subject: Optional[str] = None


@dataclass
class HitDoc:
    uuid: Optional[str]
    subject: Optional[str]
    article_title: Optional[str]
    score: Optional[float]
    raw_content: str
    citations: List[Citation] = field(default_factory=list)
    article_date_iso: Optional[str] = None
    event_dates: List[str] = field(default_factory=list)
    selectedMessage: Any = None
    highValue: Any = None


@dataclass
class EvidenceSnippet:
    uuid: str
    text: str
    date_iso: str
    article_date_iso: str
    subject: Optional[str] = None
    article_title: Optional[str] = None
    paragraph_id: Optional[str] = None
    source_id: Optional[str] = None

    # debug fields
    synonym_hits: List[str] = field(default_factory=list)
    match_policy: str = "strict"
    match_scope: str = "none"
    group_hits: int = 0
    weak_evidence: bool = False

# =========================
# JSON helpers
# =========================

def _json_load_maybe(x: Any) -> Any:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x

def _as_blocks(md: Any) -> List[dict]:
    """把 multidim_event_json 安全轉成 list[dict]。支援 str(json) / dict / list。"""
    if not md:
        return []
    md = _json_load_maybe(md)
    if isinstance(md, dict):
        return [md]
    if isinstance(md, list):
        return [b for b in md if isinstance(b, dict)]
    return []

# =========================
# Date utils (保留你現有邏輯)
# =========================

_YMD = re.compile(r'(?P<y>20\d{2}|19\d{2})[年/\-\.](?P<m>\d{1,2})[月/\-\.](?P<d>\d{1,2})日?')
_MD  = re.compile(r'(?P<m>\d{1,2})月(?P<d>\d{1,2})日')
_TODAY_D = re.compile(r'今[（(](?P<d>\d{1,2})[）)]日')
_PAREN_D = re.compile(r'[（(](?P<d>\d{1,2})日[）)]')

def _norm_date(y: int, m: int, d: int) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _normalize_iso_date(di: Any) -> Optional[str]:
    """把 date_iso 轉成 YYYY-MM-DD；容錯 list / 含時間 / 含 Z。"""
    if not di:
        return None
    if isinstance(di, list):
        if not di:
            return None
        di = di[0]
    if not isinstance(di, str):
        return None
    if len(di) < 10:
        return None
    candidate = di[:10]
    year_str = candidate[:4]
    if not year_str.isdigit():
        return None
    return candidate

def _parse_article_date_iso(raw: str) -> Optional[str]:
    if not raw:
        return None
    m = _YMD.search(raw)
    if not m:
        return None
    return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

def _collect_timeline_dates(src: dict, *, topk: int) -> List[str]:
    uniq: List[str] = []
    seen: Set[str] = set()
    blocks = _as_blocks((src or {}).get("multidim_event_json"))
    for b in blocks:
        ets = b.get("Event_Timeline") or []
        ets = _json_load_maybe(ets)
        if isinstance(ets, dict):
            ets = [ets]
        if not isinstance(ets, list):
            ets = []
        for t in ets:
            if not isinstance(t, dict):
                continue
            di = _normalize_iso_date(t.get("date_iso"))
            if di and di not in seen:
                seen.add(di)
                uniq.append(di)
                if len(uniq) >= topk:
                    return uniq
    return uniq

def _infer_date_for_snippet(text: str, article_date_iso: Optional[str], timeline_dates: List[str]) -> Optional[str]:
    if not text:
        return None
    # 1) 直接看 snippet 裡有沒有「yyyy年m月d日」
    m = _YMD.search(text)
    if m:
        return _norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

    art_y = art_m = None
    if article_date_iso and len(article_date_iso) >= 10:
        art_y = int(article_date_iso[0:4])
        art_m = int(article_date_iso[5:7])

    tl_years = sorted({int(di[0:4]) for di in timeline_dates if len(di) >= 10})

    # 2) 「x月y日」→ 帶上文章年份或 timeline 唯一年份
    m = _MD.search(text)
    if m:
        mm, dd = int(m.group('m')), int(m.group('d'))
        year = art_y or (tl_years[0] if len(tl_years) == 1 else None)
        if year:
            return _norm_date(year, mm, dd)

    # 3) 「今(12)日」、「(12日)」→
    m = _TODAY_D.search(text) or _PAREN_D.search(text)
    if m:
        dd = int(m.group('d'))
        if art_y and art_m:
            return _norm_date(art_y, art_m, dd)
        for di in timeline_dates:
            try:
                y, mm, d = int(di[0:4]), int(di[5:7]), int(di[8:10])
                if d == dd:
                    return _norm_date(y, mm, d)
            except Exception:
                continue
    return None

def _is_valid_year(di: str) -> bool:
    try:
        y = int(di[:4])
        return 1900 <= y <= 2100
    except Exception:
        return False
    
# =========================
# Snippet fallback
# =========================

def _make_fallback_snippet(text: str, q: str, width: int) -> Optional[str]:
    if not text:
        return None
    terms = [t for t in re.split(r"\s+", q or "") if t]
    positions = [text.find(t) for t in terms if t]
    pos = min([p for p in positions if p != -1] or [-1])
    if pos == -1:
        return text[:width]
    start = max(0, pos - width // 2)
    end = min(len(text), start + width)
    return text[start:end]

# =========================
# Topic matching
# =========================

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)

def _normalize_for_match(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = re.sub(r"[‐-–—−]", "-", s)
    s = re.sub(r"\s+", "", s)
    s = _PUNCT.sub("", s)
    return s


def match_topic(
    ev_text: str,
    subject: Optional[str],
    title: Optional[str],
    term_groups: List[Set[str]],
    *,
    min_groups_required: Optional[int] = None,
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
    
    回傳：ok, hit_terms, scope(text/meta/mixed), group_hits
    """
    if not term_groups:
        return True, set(), "no_filter", 0

    text_norm = _normalize_for_match(ev_text or "")
    subj_norm = _normalize_for_match(subject or "")
    title_norm = _normalize_for_match(title or "")

    hit_terms: Set[str] = set()
    group_hits = 0
    hit_in_text = False
    hit_in_meta = False

    for g in term_groups:
        if not g:
            continue
        g_hit: Set[str] = set()
        for t in g:
            if not t:
                continue
            t_norm = _normalize_for_match(t)
            if not t_norm:
                continue

            in_text = t_norm in text_norm
            in_meta = (t_norm in subj_norm) or (t_norm in title_norm)

            if in_text or in_meta:
                g_hit.add(t)
                hit_in_text = hit_in_text or in_text
                hit_in_meta = hit_in_meta or in_meta

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

    if min_groups_required is not None:
        return (group_hits >= min_groups_required), hit_terms, scope, group_hits

    n = len(term_groups)
    if n <= 1:
        return True, hit_terms, scope, group_hits
    if n == 2:
        return (group_hits == 2), hit_terms, scope, group_hits
    if n == 3:
        return (group_hits == 3), hit_terms, scope, group_hits
    return (group_hits >= 3), hit_terms, scope, group_hits

# =========================
# Evidence building (拆出純函式)
# =========================

def _build_evidence_snippet(
    h: HitDoc,
    c: Citation,
    *,
    date_from: Optional[str],
    date_to: Optional[str],
) -> Optional[EvidenceSnippet]:
    """
    把單一 hit + citation 轉成一筆 evidence_snippet：
    - 自動處理 date_iso / event_dates → article_date_iso
    - 套用 date_from / date_to 篩選
    - 帶上 uuid / subject / article_title / paragraph_id / source_id
    """
    if not c.text:
        return None

    # 日期：citation.date_iso → 文章日期 → 第一個事件日期
    di = c.date_iso or h.article_date_iso
    if not di and h.event_dates:
        di = h.event_dates[0]
    norm_di = _normalize_iso_date(di)

    if norm_di:
        if date_from and norm_di < date_from:
            return None
        if date_to and norm_di > date_to:
            return None

    article_norm = _normalize_iso_date(h.article_date_iso)
    snippet_norm = _normalize_iso_date(di)

    uuid = h.uuid or c.uuid
    if not uuid:
        return None

    return EvidenceSnippet(
        uuid=uuid,
        text=c.text,
        date_iso=(snippet_norm or article_norm or ""),
        article_date_iso=(article_norm or snippet_norm or ""),
        subject=h.subject,
        article_title=h.article_title,
        paragraph_id=c.paragraph_id,
        source_id=c.source_id,
    )

def collect_snippets(
    hits: List[HitDoc],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    term_groups: List[Set[str]],
    min_groups_required: Optional[int],
) -> List[EvidenceSnippet]:
    out: List[EvidenceSnippet] = []
    for h in hits:
        for c in h.citations:
            ev = _build_evidence_snippet(h, c, date_from=date_from, date_to=date_to)
            if ev is None:
                continue

            ok, hit_terms, scope, gh = match_topic(
                ev.text, h.subject, h.article_title, term_groups,
                min_groups_required=min_groups_required
            )
            if not ok:
                continue

            ev.match_policy = "relaxed" if min_groups_required is not None else "strict"
            ev.match_scope = scope
            ev.group_hits = gh

            if hit_terms:
                ev.synonym_hits = sorted(hit_terms)

            if scope == "meta":
                ev.weak_evidence = True

            out.append(ev)
    return out

# =========================
# ES hit -> HitDoc 整理層
# =========================

def parse_es_hits(
    es_hits: List[Dict[str, Any]],
    *,
    query_for_snippet: str,
    config: EvidenceBuildConfig,
) -> Tuple[List[HitDoc], Dict[str, int]]:
    stats = {
        "n_es_hits": len(es_hits or []),
        "n_inner_used": 0,
        "n_fallback_used": 0,
        "n_total_citations": 0,
    }

    out_hits: List[HitDoc] = []

    for h in es_hits or []:
        src = h.get("_source", {}) or {}
        raw_content = ((src.get("rawInfo") or {}).get("content") or "").strip()

        # subject
        subject = (src.get("communication", {}) or {}).get("subject")

        # article_title：從 multidim_event_json blocks 擷取（避免 str/dict/list 不一致）
        article_title = None
        blocks = _as_blocks(src.get("multidim_event_json"))
        if blocks:
            article_title = blocks[0].get("article_title")

        # timeline / article date
        tl_dates = _collect_timeline_dates(src, topk=config.timeline_dates_topk)
        article_date_iso = _parse_article_date_iso(raw_content) or (tl_dates[0] if tl_dates else None)

        # citations: inner_hits 優先
        citations: List[Citation] = []
        ih = (h.get("inner_hits") or {}).get("evi") or {}
        ih_hits = (ih.get("hits") or {}).get("hits") or []
        if ih_hits:
            for eh in ih_hits[:config.inner_hit_topk]:
                esrc = (eh.get("_source") or {})
                txt = esrc.get("text")
                sid = esrc.get("source_id")
                pid = esrc.get("paragraph_id")

                if not txt:
                    nested = (esrc.get("multidim_event_json", {}) or {}).get("evidence_snippets", {}) or {}
                    txt = nested.get("text")
                    sid = nested.get("source_id")
                    pid = nested.get("paragraph_id")

                if txt:
                    citations.append(Citation(text=txt, source_id=sid, paragraph_id=pid))

            if citations:
                stats["n_inner_used"] += 1

        # fallback
        if not citations:
            snippet = _make_fallback_snippet(raw_content, query_for_snippet or "", width=config.fallback_width)
            if snippet:
                stats["n_fallback_used"] += 1
                citations.append(Citation(text=snippet))

        stats["n_total_citations"] += len(citations)

        # per-citation date inference + attach uuid/subject
        uuid = src.get("uuid")
        for c in citations:
            di = _infer_date_for_snippet(c.text or "", article_date_iso, tl_dates)
            if di:
                c.date_iso = di
            c.uuid = uuid
            c.subject = subject

        # 清掉不合理年份
        for c in citations:
            if c.date_iso and not _is_valid_year(c.date_iso):
                c.date_iso = None

        out_hits.append(HitDoc(
            uuid=uuid,
            subject=subject,
            article_title=article_title,
            score=h.get("_score"),
            raw_content=raw_content,
            citations=citations[:config.citations_per_doc],
            article_date_iso=article_date_iso,
            event_dates=tl_dates[:config.timeline_dates_topk],
            selectedMessage=src.get("selectedMessage"),
            highValue=(((src.get("ai") or {}).get("classLabels") or {}).get("highValue")),
        ))

    return out_hits, stats

# =========================
# 高階 API：build_hits_and_evidence（乾淨主流程）
# =========================

def build_hits_and_evidence(
    es_hits: List[Dict[str, Any]],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    effective_terms: Optional[List[str]],
    term_groups: List[Set[str]],
    query_for_snippet: str,
    config: Optional[EvidenceBuildConfig] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    config = config or EvidenceBuildConfig()
    term_groups = term_groups or []
    effective_terms = effective_terms or []

    out_hits, stats = parse_es_hits(es_hits, query_for_snippet=query_for_snippet, config=config)

    logger.info(
        "build_hits_and_evidence: es_hits=%d out_hits=%d citations=%d inner_used=%d fallback_used=%d "
        "term_groups=%d effective_terms=%d date_range=%s~%s",
        stats["n_es_hits"], len(out_hits), stats["n_total_citations"], stats["n_inner_used"], stats["n_fallback_used"],
        len(term_groups), len(effective_terms),
        date_from or "N/A", date_to or "N/A",
    )

    # 1) strict
    evidence = collect_snippets(
        out_hits,
        date_from=date_from, date_to=date_to,
        term_groups=term_groups,
        min_groups_required=None,
    )
    logger.info("build_hits_and_evidence: evidence strict=%d", len(evidence))

    # 2) relax
    if not evidence and out_hits and term_groups:
        n = len(term_groups)
        strict_req = 1 if n <= 1 else (2 if n == 2 else 3)  # n>=3 -> 3
        for req in range(strict_req - 1, 0, -1):
            logger.warning(
                "build_hits_and_evidence: strict evidence=0 -> relax try (groups=%d strict_req=%d try_req=%d)",
                n, strict_req, req
            )
            tmp = collect_snippets(
                out_hits,
                date_from=date_from, date_to=date_to,
                term_groups=term_groups,
                min_groups_required=req,
            )
            logger.info("build_hits_and_evidence: evidence relaxed(req=%d)=%d", req, len(tmp))
            if tmp:
                evidence = tmp
                break

    # 3) fallback：無主題詞 → 每篇取第一段
    if not evidence and out_hits and not effective_terms:
        logger.warning("build_hits_and_evidence: evidence=0 and no effective_terms -> fallback pick first citation")
        for h in out_hits[:config.max_docs_for_fallback]:
            if not h.citations:
                continue
            ev = _build_evidence_snippet(h, h.citations[0], date_from=date_from, date_to=date_to)
            if ev:
                evidence.append(ev)
        logger.info("build_hits_and_evidence: evidence fallback(no_terms)=%d", len(evidence))

    # 4) fallback：有主題詞但 strict/relax 都 0 → any effective_term
    if not evidence and out_hits and effective_terms:
        logger.warning("build_hits_and_evidence: evidence=0 with effective_terms -> fallback contains-any-effective-term")
        eff_norm = [(_normalize_for_match(t), t) for t in effective_terms if t]
        for h in out_hits:
            for c in h.citations:
                ev = _build_evidence_snippet(h, c, date_from=date_from, date_to=date_to)
                if not ev:
                    continue
                haystack_norm = _normalize_for_match((ev.text or "") + " " + (h.subject or "") + " " + (h.article_title or ""))
                hit_terms = [orig for norm, orig in eff_norm if norm and norm in haystack_norm]
                if not hit_terms:
                    continue
                ev.match_scope = "fallback_any_term"
                ev.weak_evidence = True
                ev.synonym_hits = sorted(set(hit_terms))
                evidence.append(ev)
        logger.info("build_hits_and_evidence: evidence fallback(effective_terms)=%d", len(evidence))

    # 5) filtered_hits：只留有 evidence 的 doc
    if evidence:
        kept = {e.uuid for e in evidence if e.uuid}
        filtered = [h for h in out_hits if h.uuid in kept]
    else:
        filtered = out_hits

    syn_snippets = sum(1 for e in evidence if e.synonym_hits)
    weak_cnt = sum(1 for e in evidence if e.weak_evidence)

    logger.info(
        "build_hits_and_evidence: filtered_hits=%d evidence=%d syn_snippets=%d weak=%d",
        len(filtered), len(evidence), syn_snippets, weak_cnt
    )

    # 回到你原本的回傳型別（dict）
    filtered_hits_dict = [
        {
            "uuid": h.uuid,
            "subject": h.subject,
            "score": h.score,
            "citations": [
                {
                    "text": c.text,
                    "source_id": c.source_id,
                    "paragraph_id": c.paragraph_id,
                    **({"date_iso": c.date_iso} if c.date_iso else {}),
                    **({"uuid": c.uuid} if c.uuid else {}),
                    **({"subject": c.subject} if c.subject else {}),
                }
                for c in (h.citations or [])
            ],
            "article_date_iso": h.article_date_iso,
            "event_dates": h.event_dates,
            "event_date_span": {"min": min(h.event_dates), "max": max(h.event_dates)} if h.event_dates else None,
            "article_title": h.article_title,
            "selectedMessage": h.selectedMessage,
            "highValue": h.highValue,
        }
        for h in filtered
    ]

    evidence_dict = [
        {
            "uuid": e.uuid,
            "text": e.text,
            "date_iso": e.date_iso,
            "article_date_iso": e.article_date_iso,
            "subject": e.subject,
            "article_title": e.article_title,
            **({"paragraph_id": e.paragraph_id} if e.paragraph_id is not None else {}),
            **({"source_id": e.source_id} if e.source_id is not None else {}),
            **({"synonym_hits": e.synonym_hits} if e.synonym_hits else {}),
            "match_policy": e.match_policy,
            "match_scope": e.match_scope,
            "group_hits": e.group_hits,
            **({"weak_evidence": True} if e.weak_evidence else {}),
        }
        for e in evidence
    ]

    return filtered_hits_dict, evidence_dict, syn_snippets