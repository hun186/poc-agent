# api/core/presenters/extractors.py
from __future__ import annotations
import re
import json
from typing import Any, Dict, List, Optional

from api.core.presenters.text_sanitize import normalize_text_for_markdown
from api.core.presenters.sections import (
    AgentPresentation,
    DataAgentSection,
)

from shared.citations.citation_id import pick_doc_id

import unicodedata

def _norm_q(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s
    
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
    #print("in extract_presentation, user_question", user_question)
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
    抽出「展示用的使用者提問」（乾淨原始問句）。
    優先：out.query_meta.user_question
    次之：out.question（上游應強制覆寫為本輪 user_msg）
    再次：out.q（refined）
    最後才退回 data_agent（避免抽到拼裝）
    """
    if not isinstance(out, dict):
        return ""

    # 1) query_meta.question_raw（最乾淨、最符合「原始問句」定義）
    
    qm = out.get("query_meta")
    #print("query_meta in extract_user_question",qm)
    if isinstance(qm, dict):
        v = qm.get("user_question")
        if isinstance(v, str) and v.strip():
            #print("return v.strip() in extract_user_question",v.strip())
            return v.strip()
    
    # 2) out.question（你的 answer_with_routing 建議改成強制覆寫 out["question"]=user_msg）
    v = out.get("question")
    if isinstance(v, str) and v.strip():
        return v.strip()

    # 3) refined / 其他常見欄位（必要時才用）
    for k in ("q", "user_question", "prompt"):
        v = out.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 4) 最後才退回 data_agent：優先用 question_used/refined_question，避免 question_raw（拼裝）
    da = out.get("data_agent") or {}
    runs = da.get("runs") or []
    if runs:
        last = runs[-1] or {}
        for k in ("question_used", "refined_question"):
            v = last.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        # ⚠️ 真的沒辦法才用 question_raw（可能是拼裝）
        v = last.get("question_raw") or last.get("question")
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""
    
def extract_user_question_1230(out: dict) -> str:
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

def _extract_style_docs_from_out(out: Dict[str, Any], last_run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    風格參考全文可能出現的位置不固定：依序嘗試多個路徑。
    只要拿到 list 就回傳；否則回空 list。
    """
    cands = []

    # 1) 最常見：直接在 out 根節點
    cands.append(out.get("style_docs"))

    # 2) 有些人會包 payload
    payload = out.get("payload")
    if isinstance(payload, dict):
        cands.append(payload.get("style_docs"))

    # 3) 也有人會叫 style_payload / data_agent_payload
    style_payload = out.get("style_payload")
    if isinstance(style_payload, dict):
        cands.append(style_payload.get("style_docs"))

    da_payload = out.get("data_agent_payload")
    if isinstance(da_payload, dict):
        cands.append(da_payload.get("style_docs"))

    # 4) 最後才看 trace（通常不建議放太大，但以防萬一）
    cands.append(last_run.get("style_docs"))

    for v in cands:
        if isinstance(v, list):
            # 只保留 dict，避免怪型別把後面 docx renderer 弄炸
            return [x for x in v if isinstance(x, dict)]
    return []
    
def extract_data_agent_section(out: Dict[str, Any]) -> Optional[DataAgentSection]:
    data_agent = out.get("data_agent") or {}
    runs = data_agent.get("runs") or []
    if not runs:
        return None

    last_run = runs[-1] or {}
    mode = last_run.get("mode") or out.get("mode")
    elapsed = last_run.get("elapsed_sec")
    #question_raw = last_run.get("question") or out.get("question") or out.get("q")
    question_raw = (
        last_run.get("question_raw")
        or out.get("question_raw")
        or last_run.get("user_question")
        or out.get("user_question")
        or last_run.get("question")
        or out.get("question")
        or out.get("q")
    )

    stats = last_run.get("stats") or {}
    query_meta = last_run.get("query_meta") or {}
    time_range = last_run.get("time_range") or {}

    # ---- ✅ 新增：讀取路由/索引資訊（不要在 presenter 端推導） ----
    # 優先：last_run.query_meta（由 run_data_agent 回填）
    # 次之：out["route"]（你若依建議有放）
    # 再次：out.query_meta（相容舊資料）
    route = out.get("route") if isinstance(out.get("route"), dict) else {}
    out_qm = out.get("query_meta") if isinstance(out.get("query_meta"), dict) else {}

    topic = (
        query_meta.get("topic")
        or route.get("topic")
        or out_qm.get("topic")
    )

    idxs = (
        query_meta.get("indexes")
        or route.get("indexes")
        or out_qm.get("indexes")
        or []
    )
    if isinstance(idxs, str):
        # 允許 "a,b,c" 或 "a、b" 兩種
        if "," in idxs:
            idxs = [x.strip() for x in idxs.split(",") if x.strip()]
        elif "、" in idxs:
            idxs = [x.strip() for x in idxs.split("、") if x.strip()]
        else:
            idxs = [idxs.strip()] if idxs.strip() else []
    elif isinstance(idxs, list):
        idxs = [str(x).strip() for x in idxs if str(x).strip()]
    else:
        idxs = []

    index_hint = (
        query_meta.get("index_hint")
        or route.get("index_hint")
        or out_qm.get("index_hint")
    )
    if isinstance(index_hint, list):
        index_hint = ",".join([str(x).strip() for x in index_hint if str(x).strip()])
    if not isinstance(index_hint, str):
        index_hint = None
        
    core_terms = (query_meta.get("core_terms") or last_run.get("core_terms") or []) or []
    topic_terms = (query_meta.get("topic_terms") or last_run.get("topic_terms") or []) or []
    style_terms = (query_meta.get("style_terms") or last_run.get("style_terms") or []) or []

    syn_terms = (query_meta.get("syn_terms") or []) or []
    effective_terms = (query_meta.get("effective_terms") or []) or []

    dt_from = time_range.get("date_from") or query_meta.get("date_from")
    dt_to = time_range.get("date_to") or query_meta.get("date_to")

    # 檢索用 query：照舊（style_query/core_query 都放這邊）
    es_query = query_meta.get("es_query") or query_meta.get("core_query")
    if str(mode or "").lower() in ("style", "sra_style") and not es_query:
        es_query = last_run.get("style_query")

    # ✅ 精煉提問：只接受「真的有 refined_question」才算
    rq = last_run.get("refined_question") or out.get("refined_question")
    refined_question = None
    if isinstance(rq, str) and rq.strip():
        # 可選：避免同句也顯示
        if _norm_q(rq) != _norm_q(question_raw if isinstance(question_raw, str) else ""):
            refined_question = rq.strip()
    
    # ✅ 新增：抽出 style_docs（只在 style / sra_style 時通常有）
    style_docs = _extract_style_docs_from_out(out, last_run)
    
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
        # ✅ 新增
        topic=str(topic).strip() if isinstance(topic, str) and topic.strip() else None,
        indexes=idxs,
        index_hint=index_hint.strip() if isinstance(index_hint, str) and index_hint.strip() else None,

        # ✅ 只在真的精煉時才有值；風格模式不會被 style_query 汙染
        refined_question=refined_question,
        
        # ✅ 新增欄位
        style_docs=style_docs,
    )
