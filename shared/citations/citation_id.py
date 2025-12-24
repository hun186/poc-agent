# shared/citations/citation_id.py
from __future__ import annotations

from typing import Any, Dict, Optional


def pick_doc_id(c: Dict[str, Any]) -> Optional[str]:
    """
    統一挑 citation/snippet 的文件識別欄位。

    優先序：
    - uuid
    - source_id
    - doc_id
    - id
    """
    v = c.get("uuid") or c.get("source_id") or c.get("doc_id") or c.get("id")
    if v is None:
        return None
    if isinstance(v, str) and v.strip():
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    return str(v) if v else None