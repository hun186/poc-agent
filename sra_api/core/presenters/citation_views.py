# api/core/presenters/citation_views.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import Request
from api.core.url_utils import abs_url
from api.security.signed_urls import sign_resource
from urllib.parse import urlencode

#from shared.citations.citation_id import pick_doc_id
from shared.citations.citation_view_core import build_citation_core_views

@dataclass(frozen=True)
class CitationView:
    doc_id: Optional[str]
    label: str                 # "3." or "-"
    display: str               # subject/title/doc_id fallback
    paragraph_id: Optional[Any]
    date_iso: Optional[str]
    short_text: str            # single-line + truncated
    url_es: Optional[str]
    url_json: Optional[str]
    url_txt: Optional[str]
    url_raw_txt: Optional[str]
    url_both_txt: Optional[str]

def build_citation_views(
    citations: List[dict],
    request: Request,
    *,
    text_limit: int = 300,
) -> List[CitationView]:
    """
    API layer:
    - core：統一 label/display/short_text/doc_id（shared）
    - 這層只負責補 URL（跟 Request 綁定）
    """
    cores = build_citation_core_views(citations, text_limit=text_limit)

    views: List[CitationView] = []
    for c in cores:
        url_es = url_json = url_txt = url_raw_txt = url_both_txt = None
        if isinstance(c.doc_id, str) and c.doc_id:
            base_full = abs_url(request, f"/v1/docs/{c.doc_id}/fulltext")
            def full(fmt, download, layer):
                return base_full + "?" + urlencode({"format": fmt, "download": download, "text_layer": layer,
                    "sig": sign_resource("doc_fulltext", doc_id=c.doc_id, format=fmt, download=download, text_layer=layer)})
            url_json = full("json", "0", "both")
            url_txt = full("txt", "1", "reference")
            url_raw_txt = full("txt", "1", "raw")
            url_both_txt = full("txt", "1", "both")
            url_es = abs_url(request, f"/v1/docs/{c.doc_id}?{urlencode({'sig': sign_resource('doc_detail', doc_id=c.doc_id)})}")

        views.append(
            CitationView(
                doc_id=c.doc_id,
                label=c.label,
                display=c.display,
                paragraph_id=c.paragraph_id,
                date_iso=c.date_iso,
                short_text=c.short_text,
                url_es=url_es,
                url_json=url_json,
                url_txt=url_txt,
                url_raw_txt=url_raw_txt,
                url_both_txt=url_both_txt,
            )
        )

    return views

'''
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
    # ★ 這裡只做顯示用壓成一行與截斷；不要再 normalize（extract_citations 已做）
    s = (text or "")
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\n", " ").strip()
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


def build_citation_views(
    citations: List[Dict[str, Any]],
    request: Request,
) -> List[CitationView]:
    views: List[CitationView] = []
    for c in citations or []:
        if not isinstance(c, dict):
            continue

        doc_id = pick_doc_id(c)
        label = _build_label(c)
        display = _build_display(c, doc_id)
        pid = c.get("paragraph_id")
        date_iso = c.get("date_iso") if isinstance(c.get("date_iso"), str) else None
        short_text = _shorten_text(c.get("text"))

        url_es = url_json = url_txt = None
        if isinstance(doc_id, str) and doc_id:
            base_full = abs_url(request, f"/v1/docs/{doc_id}/fulltext")
            url_json = base_full + "?format=json"
            url_txt = base_full + "?format=txt&download=1"
            url_es = abs_url(request, f"/v1/docs/{doc_id}")

        views.append(
            CitationView(
                doc_id=doc_id,
                label=label,
                display=display,
                paragraph_id=pid,
                date_iso=date_iso,
                short_text=short_text,
                url_es=url_es,
                url_json=url_json,
                url_txt=url_txt,
            )
        )
    return views
'''
