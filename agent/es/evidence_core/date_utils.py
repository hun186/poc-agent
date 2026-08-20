#agent/es/evidence_core/date_utils.py
from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from .json_utils import as_blocks, json_load_maybe


_YMD = re.compile(r'(?P<y>20\d{2}|19\d{2})[年/\-\.](?P<m>\d{1,2})[月/\-\.](?P<d>\d{1,2})日?')
_MD  = re.compile(r'(?P<m>\d{1,2})月(?P<d>\d{1,2})日')
_TODAY_D = re.compile(r'今[（(](?P<d>\d{1,2})[）)]日')
_PAREN_D = re.compile(r'[（(](?P<d>\d{1,2})日[）)]')


def norm_date(y: int, m: int, d: int) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def normalize_iso_date(di: Any) -> Optional[str]:
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


def parse_article_date_iso(raw: str) -> Optional[str]:
    if not raw:
        return None
    m = _YMD.search(raw)
    if not m:
        return None
    return norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))


def collect_timeline_dates(src: dict, *, topk: int) -> List[str]:
    uniq: List[str] = []
    seen: Set[str] = set()
    blocks = as_blocks((src or {}).get("multidim_event_json"))
    for b in blocks:
        ets = b.get("Event_Timeline") or []
        ets = json_load_maybe(ets)
        if isinstance(ets, dict):
            ets = [ets]
        if not isinstance(ets, list):
            ets = []
        for t in ets:
            if not isinstance(t, dict):
                continue
            di = normalize_iso_date(t.get("time_iso"))
            if di and di not in seen:
                seen.add(di)
                uniq.append(di)
                if len(uniq) >= topk:
                    return uniq
    return uniq


def infer_date_for_snippet(text: str, article_date_iso: Optional[str], timeline_dates: List[str]) -> Optional[str]:
    if not text:
        return None
    # 1) 直接看 snippet 裡有沒有「yyyy年m月d日」
    m = _YMD.search(text)
    if m:
        return norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

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
            return norm_date(year, mm, dd)

    # 3) 「今(12)日」、「(12日)」→
    m = _TODAY_D.search(text) or _PAREN_D.search(text)
    if m:
        dd = int(m.group('d'))
        if art_y and art_m:
            return norm_date(art_y, art_m, dd)
        for di in timeline_dates:
            try:
                y, mm, d = int(di[0:4]), int(di[5:7]), int(di[8:10])
                if d == dd:
                    return norm_date(y, mm, d)
            except Exception:
                continue

    return None


def is_valid_year(di: str) -> bool:
    try:
        y = int(di[:4])
        return 1900 <= y <= 2100
    except Exception:
        return False
