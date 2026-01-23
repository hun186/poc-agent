#agent/es/evidence_core/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


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
    date_iso: Optional[str] = None
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

    synonym_hits: List[str] = field(default_factory=list)
    match_policy: str = "strict"
    match_scope: str = "none"
    group_hits: int = 0
    weak_evidence: bool = False
