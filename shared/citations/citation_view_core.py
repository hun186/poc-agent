# shared/citations/citation_view_core.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from shared.citations.citation_id import pick_doc_id


@dataclass(frozen=True)
class CitationCoreView:
    doc_id: Optional[str]
    label: str                 # "3." or "-"
    display: str               # subject/title/doc_id fallback
    paragraph_id: Optional[Any]
    date_iso: Optional[str]
    short_text: str            # single-line + truncated


def _build_label(c: Dict[str, Any]) -> str:
    ref_no = c.get("ref_no")
    if not isinstance(ref_no, int):
        ref_no = c.get("snippet_index") if isinstance(c.get("snippet_index"), int) else None
    return f"{ref_no}." if isinstance(ref_no, int) else "-"


def _build_display(c: Dict[str, Any], doc_id: Optional[str]) -> str:
    return (
        c.get("subject")
        or c.get("article_title")
        or c.get("title")
        or (str(doc_id) if doc_id is not None else "[未知來源]")
    )


def _shorten_text(text: Any, *, limit: int = 300) -> str:
    s = text or ""
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\n", " ").strip()
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


def build_citation_core_views(
    citations: List[Dict[str, Any]],
    *,
    text_limit: int = 300,
) -> List[CitationCoreView]:
    """
    只做「顯示用視圖」：
    - 統一 pick_doc_id
    - 統一 label/display/short_text
    - 不包含 URL（URL 是 API layer 才該做的事）
    """
    views: List[CitationCoreView] = []

    for c in citations or []:
        if not isinstance(c, dict):
            continue

        doc_id = pick_doc_id(c)
        label = _build_label(c)
        display = _build_display(c, doc_id)
        pid = c.get("paragraph_id")
        date_iso = c.get("date_iso") if isinstance(c.get("date_iso"), str) else None
        short_text = _shorten_text(c.get("text"), limit=text_limit)

        views.append(
            CitationCoreView(
                doc_id=doc_id,
                label=label,
                display=display,
                paragraph_id=pid,
                date_iso=date_iso,
                short_text=short_text,
            )
        )

    return views
