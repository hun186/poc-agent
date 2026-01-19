# agent/data_agent/runtime.py
from __future__ import annotations

import re
import time
import logging
from typing import Any, Dict, Optional, List, Tuple

from .builder import build_agent, normalize_model_id
from .types import ENV

logger = logging.getLogger(__name__)

_SYS_PARAM_BLOCK_HEAD = "【系統參數（抽取關鍵字時請忽略本段）】"
_USER_Q_BLOCK_HEAD = "【使用者問題】"


def _pack_question_for_agent(question: str, index_hint: Optional[str]) -> str:
    question = question or ""
    if not index_hint:
        return question

    sys_lines = [f"index_hint={index_hint}"]
    return (
        f"{_SYS_PARAM_BLOCK_HEAD}\n"
        + "\n".join(sys_lines)
        + f"\n\n{_USER_Q_BLOCK_HEAD}\n"
        + question
    )


def _extract_payload(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict) and "payload" in result and isinstance(result["payload"], dict):
        return result["payload"]
    if isinstance(result, dict):
        return result
    raise ValueError("資料代理人回傳格式非 dict，請檢查 CodeAgent 的 final_answer 使用方式。")


def _get_query_meta_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    盡量保留既有結構：
      1) payload["query_meta"]
      2) payload["raw_search_result"]["query_meta"]
    """
    qm: Dict[str, Any] = {}
    p_qm = payload.get("query_meta")
    if isinstance(p_qm, dict):
        qm.update(p_qm)
        return qm

    raw = payload.get("raw_search_result")
    if isinstance(raw, dict):
        raw_qm = raw.get("query_meta")
        if isinstance(raw_qm, dict):
            qm.update(raw_qm)
    return qm


def _norm_compare_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("，", ",").replace("。", ".").replace("：", ":")
    return s


def _apply_route_meta(payload: Dict[str, Any], route: Optional[Dict[str, Any]], index_hint: Optional[str]) -> None:
    if not isinstance(route, dict) or not route:
        return

    route_topic = route.get("topic")
    route_indexes = route.get("indexes")
    route_index_hint = route.get("index_hint") or index_hint

    payload["route"] = {
        "topic": route_topic,
        "indexes": route_indexes,
        "index_hint": route_index_hint,
    }

    if not isinstance(payload.get("query_meta"), dict):
        payload["query_meta"] = {}

    if route_topic:
        payload["query_meta"]["topic"] = route_topic
    if route_indexes:
        payload["query_meta"]["indexes"] = route_indexes
    if route_index_hint:
        payload["query_meta"]["index_hint"] = route_index_hint


def _apply_question_meta(
    payload: Dict[str, Any],
    *,
    mode: str,
    question_input: str,
    question_raw: Optional[str],
    refined_question: Optional[str],
) -> Tuple[str, str]:
    mode_norm = (mode or "").strip().lower()

    q_raw = (question_raw or payload.get("question_raw") or question_input or "").strip()

    q_ref = (refined_question or "").strip()
    if not q_ref:
        qm = _get_query_meta_from_payload(payload)
        q_ref = (qm.get("refined_question") or payload.get("refined_question") or "").strip()

    # style：預設不開 refined（除非上游真的傳 refined_question）
    if mode_norm in ("style", "sra_style") and not (refined_question or "").strip():
        q_ref = ""

    if q_ref and _norm_compare_text(q_ref) == _norm_compare_text(q_raw):
        q_ref = ""

    if not isinstance(payload.get("query_meta"), dict):
        payload["query_meta"] = {}
    payload["query_meta"]["question_raw"] = (q_raw or None)
    payload["query_meta"]["refined_question"] = (q_ref or None)

    return q_raw, q_ref


def _trace_append_run(
    trace: Dict[str, Any],
    *,
    mode: str,
    elapsed: float,
    question_for_agent: str,
    question_used: str,
    question_raw: str,
    refined_question: str,
    index_hint: Optional[str],
    route: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
) -> None:
    try:
        da_root = trace.setdefault("data_agent", {})
        runs: List[Dict[str, Any]] = da_root.setdefault("runs", [])

        mode_norm = (mode or "").strip().lower()
        query_meta = _get_query_meta_from_payload(payload)

        run_info: Dict[str, Any] = {
            "mode": mode,
            "elapsed_sec": round(elapsed, 3),
            "model_id": ENV.data_agent_model_id,
            "model_id_effective": normalize_model_id(ENV.data_agent_model_id),
            "question_raw": question_raw or None,
            "refined_question": refined_question or None,
            "question_used": question_used or None,
            "index_hint": index_hint,
            "question_for_agent": question_for_agent,
        }

        if isinstance(route, dict) and route:
            run_info["route"] = {
                "topic": route.get("topic"),
                "indexes": route.get("indexes"),
                "index_hint": route.get("index_hint") or index_hint,
            }

        if query_meta:
            run_info["query_meta"] = query_meta

        # report 模式：抓常用欄位
        if mode_norm in ("report", "sra_report"):
            time_range = payload.get("time_range") or {}
            stats = payload.get("stats") or {}

            run_info["time_range"] = {
                "date_from": time_range.get("date_from"),
                "date_to": time_range.get("date_to"),
            }
            run_info["stats"] = {
                "doc_count": stats.get("doc_count"),
                "snippet_count": stats.get("snippet_count"),
                "active_days": stats.get("active_days"),
            }
            run_info["core_terms"] = query_meta.get("core_terms") or []
            run_info["date_from"] = query_meta.get("date_from")
            run_info["date_to"] = query_meta.get("date_to")

        # style 模式：terms 以 payload 優先，其次 query_meta
        elif mode_norm in ("style", "sra_style"):
            stats = payload.get("stats") or {}

            style_terms = payload.get("style_terms") or query_meta.get("style_terms") or []
            topic_terms = payload.get("topic_terms") or query_meta.get("topic_terms") or []
            core_terms = payload.get("core_terms") or query_meta.get("core_terms") or []

            run_info["style_query"] = payload.get("style_query")
            run_info["stats"] = {
                "doc_count": stats.get("doc_count"),
                "snippet_count": stats.get("snippet_count"),
                "full_doc_count": stats.get("full_doc_count"),
            }
            run_info["style_terms"] = style_terms
            run_info["topic_terms"] = topic_terms
            run_info["core_terms"] = core_terms
            run_info["date_from"] = payload.get("date_from") or query_meta.get("date_from")
            run_info["date_to"] = payload.get("date_to") or query_meta.get("date_to")

        else:
            run_info["extra"] = {"keys_in_payload": list(payload.keys())}

        runs.append(run_info)

    except Exception as e:
        logger.debug("[data_agent] trace logging error: %s", e)


def run_data_agent(
    question: str,
    mode: str = "report",
    trace: Optional[Dict[str, Any]] = None,
    *,
    question_raw: Optional[str] = None,
    refined_question: Optional[str] = None,
    index_hint: Optional[str] = None,
    route: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    共用一個 CodeAgent 建立邏輯，只是 SYSTEM 不同：
      - mode="report"：做 SRA_REPORT 的資料準備
      - mode="style" ：做 SRA_STYLE 的風格語料準備

    行為重點：
      - 保留模型共用、Agent 每次新建
      - payload/query_meta 補齊 question_raw/refined_question/route
      - trace 記錄集中化，不影響主流程
    """
    if trace is None:
        trace = {}

    t0 = time.time()
    code_agent = build_agent(mode=mode)

    question_for_agent = _pack_question_for_agent(question or "", index_hint=index_hint)
    result = code_agent.run(question_for_agent)
    elapsed = time.time() - t0

    payload = _extract_payload(result)

    # 盡量避免覆寫：若 query_meta 不是 dict，先補成 dict
    if not isinstance(payload.get("query_meta"), dict):
        payload["query_meta"] = {}

    # route/topic/indexes 寫回 payload（以「上游 router」為準）
    _apply_route_meta(payload, route=route, index_hint=index_hint)

    # raw/refined 補強（style 預設不顯示 refined，除非上游真的傳）
    q_used = (payload.get("question") or question or "").strip()
    q_raw, q_ref = _apply_question_meta(
        payload,
        mode=mode,
        question_input=(question or ""),
        question_raw=question_raw,
        refined_question=refined_question,
    )

    # trace（失敗不影響主流程）
    _trace_append_run(
        trace,
        mode=mode,
        elapsed=elapsed,
        question_for_agent=question_for_agent,
        question_used=q_used,
        question_raw=q_raw,
        refined_question=q_ref,
        index_hint=index_hint,
        route=route,
        payload=payload,
    )

    return payload
