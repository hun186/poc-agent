#agent/es/evidence_core/json_utils.py
from __future__ import annotations

import json
from typing import Any, List


def json_load_maybe(x: Any) -> Any:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


def as_blocks(md: Any) -> List[dict]:
    """
    把 multidim_event_json 安全轉成 list[dict]。支援 str(json) / dict / list。
    """
    if not md:
        return []
    md = json_load_maybe(md)
    if isinstance(md, dict):
        return [md]
    if isinstance(md, list):
        return [b for b in md if isinstance(b, dict)]
    return []
