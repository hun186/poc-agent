# agent/doc_followup/slicer.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from .config import DocFollowupConfig
from .planner import plan_ranges_with_llm
from .parsing import parse_target_index, parse_char_range_1based


def slice_docs_for_instruction(cfg: DocFollowupConfig, instruction: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    - 優先使用 LLM planner 的 plans
    - 失敗 fallback：regex 解析第幾篇 + 字元範圍
    - 每篇會帶 range(1-based, inclusive) + total_length
    """
    if not docs:
        return []

    docs = docs[: cfg.max_docs]

    idx2doc = {d.get("index"): d for d in docs}

    remaining = cfg.max_total_chars
    sliced: List[Dict[str, Any]] = []

    def _apply_slice_by_range(d: Dict[str, Any], start_1: int, end_1: int) -> Optional[Dict[str, Any]]:
        nonlocal remaining
        text = d.get("full_text") or ""
        if not text:
            return None

        total_len = len(text)

        # 1-based inclusive -> 0-based half-open
        s0 = max(0, start_1 - 1)
        e0 = min(end_1, total_len)  # end_1 是 inclusive，但這裡當作 e0 = inclusive index -> slice end 直接用 e0
        if e0 <= s0:
            return None

        seg_len = e0 - s0
        if seg_len <= 0 or remaining <= 0:
            return None

        if seg_len > remaining:
            e0 = s0 + remaining
            seg_len = remaining

        segment_text = text[s0:e0]
        remaining -= seg_len

        nd = dict(d)
        nd["full_text"] = segment_text
        nd["range"] = {"start": s0 + 1, "end": e0}   # e0 是 slice end（0-based），剛好等於 1-based inclusive end
        nd["total_length"] = total_len
        return nd

    # ===== 1) Planner =====
    plans = plan_ranges_with_llm(cfg, instruction, docs)
    if plans:
        for p in plans:
            if remaining <= 0:
                break
            d = idx2doc.get(p.get("index"))
            if not d:
                continue
            sd = _apply_slice_by_range(d, int(p["start"]), int(p["end"]))
            if sd:
                sliced.append(sd)

        if sliced:
            return sliced

    # ===== 2) Regex fallback =====
    target_idx = parse_target_index(instruction)
    start_1, end_1 = parse_char_range_1based(instruction, max_total_chars=cfg.max_total_chars)

    def _slice_one(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if start_1 is None and end_1 is None:
            return _apply_slice_by_range(d, 1, cfg.max_total_chars)
        return _apply_slice_by_range(d, start_1 or 1, end_1 or (start_1 or 1) + cfg.max_total_chars - 1)

    if target_idx is not None:
        d = idx2doc.get(target_idx)
        if d:
            sd = _slice_one(d)
            if sd:
                sliced.append(sd)
            return sliced

    # 沒指定第幾篇：依序切，直到用滿
    for d in docs:
        if remaining <= 0:
            break
        sd = _slice_one(d)
        if sd:
            sliced.append(sd)

    # 最後防呆：真的切不到，就至少切第一篇開頭
    if not sliced:
        d0 = docs[0]
        text0 = d0.get("full_text") or ""
        if text0:
            use_len = min(len(text0), cfg.max_total_chars)
            nd = dict(d0)
            nd["full_text"] = text0[:use_len]
            nd["range"] = {"start": 1, "end": use_len}
            nd["total_length"] = len(text0)
            sliced.append(nd)

    return sliced
