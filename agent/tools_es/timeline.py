# agent/tools_es/timeline.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from elasticsearch import BadRequestError
from smolagents import Tool

from agent.es.es_client import safe_search as _safe_es_search
from agent.es.evidence_core.json_utils import as_blocks

from .common import resolve_index, dbg, propagate_requirement_acceptance


class ESTimeline(Tool):
    name = "es_timeline"
    description = "讀取指定 uuid 的事件時間線，回傳 event_ids、time_iso、time_raw、time_precision 與 description。"

    inputs = {
        "uuid": {
            "type": "string",
            "description": "要讀取之文件的 uuid（對應索引中的 uuid.keyword）",
            "nullable": True
        },
        "k": {
            "type": "integer",
            "description": "最多回傳多少筆時間線事件（1–60；預設 40）",
            "default": 40,
            "minimum": 1,
            "maximum": 60,
            "nullable": True
        },
        # ★ 新增：和 es_search_news 一樣吃分流 hint
        "index_hint": {
            "type": "string",
            "description": "由 LLM 分流傳入的索引提示字串；若未提供則使用環境變數 ES_INDEX",
            "nullable": True
        },
    }

    output_type = "any"

    @propagate_requirement_acceptance
    def forward(self, uuid: Optional[str] = None, k: Optional[int] = 40, index_hint: Optional[str] = None) -> Dict[str, Any]:
        if not uuid:
            return {"timeline": [], "error": "uuid is required"}

        index = resolve_index(index_hint)
        dbg("[es_timeline] index =", index, "uuid =", uuid)

        try:
            res = _safe_es_search(
                {
                    "size": 1,
                    "query": {"term": {"uuid.keyword": uuid}},
                    "_source": ["multidim_event_json.Event_Timeline"],
                },
                index=index,
                allow_highlight_retry=False,
            )
        except BadRequestError as e:
            print("[es_timeline] ES BadRequestError:", getattr(e, "info", e))
            raise

        items: List[Dict[str, Any]] = []
        hits = ((res.get("hits") or {}).get("hits") or []) if isinstance(res, dict) else []
        if hits:
            src0 = hits[0].get("_source") or {}
            blocks = as_blocks(src0.get("multidim_event_json"))
            for b in blocks:
                ets = b.get("Event_Timeline") or []
                if isinstance(ets, str):
                    try:
                        ets = json.loads(ets)
                    except Exception:
                        ets = []
                if isinstance(ets, dict):
                    ets = [ets]
                for t in ets:
                    if not isinstance(t, dict):
                        continue
                    items.append(
                        {
                            "event_ids": t.get("event_ids") or [],
                            "time_iso": t.get("time_iso"),
                            "time_raw": t.get("time_raw"),
                            "time_precision": t.get("time_precision"),
                            "description": t.get("description"),
                        }
                    )

        items = [i for i in items if i.get("time_iso")]
        items.sort(key=lambda x: x["time_iso"])
        return {"timeline": items[: (k or 40)]}
