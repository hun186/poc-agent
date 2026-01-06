# api/core/presenters/sections.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass(frozen=True)
class DataAgentSection:
    mode: Optional[str]
    elapsed_sec: Optional[float]
    question_raw: Optional[str]
    date_from: Optional[str]
    date_to: Optional[str]
    stats: Dict[str, Any]
    core_terms: List[str]
    topic_terms: List[str]
    style_terms: List[str]
    syn_terms: List[str]
    effective_terms: List[str]
    es_query: Optional[str]
    # ✅ 新增：本輪檢索標的（由 router 決策 / data_agent 回填）
    topic: Optional[str] = None
    indexes: List[str] = field(default_factory=list)
    index_hint: Optional[str] = None
    # ✅ 新增：精煉後問題（檢索用 / core_query 或 style_query）
    refined_question: Optional[str] = None
    # ✅ 新增：風格模式用的參考全文（對應 payload["style_docs"]）
    style_docs: List[Dict[str, Any]] = field(default_factory=list)
    
# ★ 新增：統一給 markdown / docx 共用的 presentation
@dataclass(frozen=True)
class AgentPresentation:
    turn_id: Optional[str]
    user_question: str
    answer: str
    reasoning: str
    citations: List[Dict[str, Any]]
    da_section: Optional[DataAgentSection]

    raw_json_str: str
    raw_json_line_count: int
    auto_collapse_json: bool
    raw_json_md: str  # 已包好 ```json 的 Markdown block
    
    