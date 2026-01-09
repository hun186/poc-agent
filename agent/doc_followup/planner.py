# agent/doc_followup/planner.py
from __future__ import annotations
from typing import Any, Dict, List
import json

from ..llm_utils.ollama_client import call_llm
from .config import DocFollowupConfig
from .prompts import build_planner_system_prompt


def plan_ranges_with_llm(cfg: DocFollowupConfig, instruction: str, docs: List[Dict[str, Any]]) -> List[Dict[str, int]]:
    """
    用 LLM planner 決定每篇要切的字元範圍。
    回傳：
      [{"index": 1, "start": 1, "end": 26000}, ...]
    失敗回 []，讓 slicer fallback。
    """
    if not docs:
        return []

    # 只給 meta，避免把全文塞進 planner prompt
    docs_meta = []
    for d in docs:
        text = d.get("full_text") or ""
        docs_meta.append(
            {
                "index": d.get("index"),
                "uuid": d.get("uuid"),
                "title": d.get("title"),
                "date": d.get("date"),
                "subject": d.get("subject"),
                "total_length": len(text),
            }
        )

    payload = {"instruction": instruction, "docs_meta": docs_meta}
    user_prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    sys_prompt = build_planner_system_prompt(cfg)

    try:
        raw = call_llm(
            user_prompt,
            system_prompt=sys_prompt,
            extra_params={"options": {}},
            timeout=cfg.planner_timeout_sec,
        )
        obj = json.loads(raw)
        plans = obj.get("plans") or []

        out: List[Dict[str, int]] = []
        used = 0

        for p in plans:
            try:
                idx = int(p["index"])
                start = int(p["start"])
                end = int(p["end"])
            except Exception:
                continue

            if start < 1 or end < start:
                continue

            length = end - start + 1
            if length <= 0:
                continue

            # 全局上限：超過就縮短
            if used + length > cfg.max_total_chars:
                remain = cfg.max_total_chars - used
                if remain <= 0:
                    break
                end = start + remain - 1
                length = remain

            out.append({"index": idx, "start": start, "end": end})
            used += length

            if used >= cfg.max_total_chars:
                break

        return out
    except Exception as e:
        print("[doc_followup] planner LLM failed:", e)
        return []
