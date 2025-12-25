# api/core/presenters/extractors.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from api.core.presenters.text_sanitize import normalize_text_for_markdown
from api.core.presenters.sections import (
    AgentPresentation,
    DataAgentSection,
)

from shared.citations.citation_id import pick_doc_id

def extract_presentation(
    out: Any,
    *,
    json_collapse_threshold: int = 60,
) -> AgentPresentation:
    """
    集中抽資料 + 正規化 + raw_json 行數判斷。
    - render_markdown() 與 ExportWordService 共用
    """
    if not isinstance(out, dict):
        # 這裡仍回傳 presentation，讓呼叫端更單純
        s = normalize_text_for_markdown(out)
        raw_json_str = json.dumps({"answer": s}, ensure_ascii=False, indent=2)
        line_count = raw_json_str.count("\n") + 1
        raw_json_md = f"```json\n{raw_json_str}\n```"
        return AgentPresentation(
            user_question="",
            answer=s,
            reasoning="",
            citations=[],
            da_section=None,
            raw_json_str=raw_json_str,
            raw_json_line_count=line_count,
            auto_collapse_json=(line_count > json_collapse_threshold),
            raw_json_md=raw_json_md,
            turn_id=None,  # ✅ 新增
        )

    user_question = extract_user_question(out)
    citations = extract_citations(out)  # 已 dedupe + normalize(text)
    da_section = extract_data_agent_section(out)

    answer = normalize_text_for_markdown(out.get("answer") or "")
    reasoning = normalize_text_for_markdown(out.get("reasoning") or "")

    raw_json_str = json.dumps(out, ensure_ascii=False, indent=2)
    line_count = raw_json_str.count("\n") + 1
    auto_collapse = line_count > json_collapse_threshold
    raw_json_md = f"```json\n{raw_json_str}\n```"
    turn_id = out.get("turn_id") or out.get("request_id")
    if turn_id is not None:
        turn_id = str(turn_id)
    return AgentPresentation(
        user_question=user_question,
        answer=answer,
        reasoning=reasoning,
        citations=citations,
        da_section=da_section,
        raw_json_str=raw_json_str,
        raw_json_line_count=line_count,
        auto_collapse_json=auto_collapse,
        raw_json_md=raw_json_md,
        turn_id=turn_id,  # ✅ 新增
    )

def extract_user_question(out: dict) -> str:
    """
    盡量從 out 裡抽出這次回答對應的「使用者提問」。
    優先：data_agent.runs[-1].question
    次之：out.question / out.q
    """
    if not isinstance(out, dict):
        return ""

    # 1) data_agent
    da = out.get("data_agent") or {}
    runs = da.get("runs") or []
    if runs:
        last = runs[-1] or {}
        q = last.get("question")
        if isinstance(q, str) and q.strip():
            return q.strip()

    # 2) out 本體
    for k in ("question", "q", "user_question", "prompt"):
        v = out.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""

def dedupe_citations(citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    去掉完全重複（同 doc_id + paragraph_id + text）
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        #doc_id = pick_doc_id(c) or ""
        doc_id = pick_doc_id(c) or f"__noid__:{id(c)}"
        key = (doc_id, c.get("paragraph_id"), c.get("text"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out

def extract_citations(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    取 citations 並把 text 正規化（避免 <em> 顯示問題）。
    """
    citations = out.get("citations") or []
    normed: List[Dict[str, Any]] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        c2 = dict(c)
        if isinstance(c2.get("text"), str):
            c2["text"] = normalize_text_for_markdown(c2["text"])
        normed.append(c2)
    return dedupe_citations(normed)

def extract_data_agent_section(out: Dict[str, Any]) -> Optional[DataAgentSection]:
    data_agent = out.get("data_agent") or {}
    runs = data_agent.get("runs") or []
    if not runs:
        return None

    last_run = runs[-1] or {}
    mode = last_run.get("mode") or out.get("mode")
    elapsed = last_run.get("elapsed_sec")
    question_raw = last_run.get("question") or out.get("question") or out.get("q")

    stats = last_run.get("stats") or {}
    query_meta = last_run.get("query_meta") or {}
    time_range = last_run.get("time_range") or {}

    core_terms = (query_meta.get("core_terms") or last_run.get("core_terms") or []) or []
    topic_terms = (query_meta.get("topic_terms") or last_run.get("topic_terms") or []) or []
    style_terms = (query_meta.get("style_terms") or last_run.get("style_terms") or []) or []

    syn_terms = (query_meta.get("syn_terms") or []) or []
    effective_terms = (query_meta.get("effective_terms") or []) or []

    dt_from = time_range.get("date_from") or query_meta.get("date_from")
    dt_to = time_range.get("date_to") or query_meta.get("date_to")

    es_query = query_meta.get("es_query") or query_meta.get("core_query")
    if str(mode or "").lower() in ("style", "sra_style") and not es_query:
        es_query = last_run.get("style_query")

    return DataAgentSection(
        mode=str(mode) if mode is not None else None,
        elapsed_sec=float(elapsed) if isinstance(elapsed, (int, float)) else None,
        question_raw=str(question_raw) if isinstance(question_raw, str) else None,
        date_from=str(dt_from) if isinstance(dt_from, str) else None,
        date_to=str(dt_to) if isinstance(dt_to, str) else None,
        stats=stats if isinstance(stats, dict) else {},
        core_terms=[str(x) for x in core_terms if isinstance(x, str)],
        topic_terms=[str(x) for x in topic_terms if isinstance(x, str)],
        style_terms=[str(x) for x in style_terms if isinstance(x, str)],
        syn_terms=[str(x) for x in syn_terms if isinstance(x, str)],
        effective_terms=[str(x) for x in effective_terms if isinstance(x, str)],
        es_query=str(es_query) if isinstance(es_query, str) else None,
    )
