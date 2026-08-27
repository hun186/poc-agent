# agent/tools_es/fetch_doc.py
from __future__ import annotations

from typing import Any, Dict, Optional

from elasticsearch import NotFoundError
from smolagents import Tool

from agent.es.es_client import get_es
from agent.es.reference_text import get_reference_text, get_reference_text_field

from .common import resolve_index, split_indexes, dbg


class ESFetchDocById(Tool):
    """
    依 uuid 從 Elasticsearch 撈出「單篇完整文件」，主要提供風格學習 / 公文範例用。

    - 預期 index 內有欄位 uuid（或 _id 就是 uuid）
    - 代理人參考文本欄位可由 text_field 指定，預設讀取 SRA_REFERENCE_TEXT_FIELD
    """
    name = "es_fetch_doc_by_id"
    description = "依 uuid 從 Elasticsearch 撈出完整文件內文，供風格寫作或報告範例參考。"

    inputs = {
        "uuid": {
            "type": "string",
            "description": "文件的 uuid 欄位值（對應索引中的 uuid 或 _id）。",
        },
        "index_hint": {
            "type": "string",
            "description": "可選：指定要查的 index（或多個 index，用逗號分隔）；未提供則走預設 ES_INDEX。",
            "nullable": True,
        },
        "text_field": {
            "type": "string",
            "description": (
                "可選：主要內文欄位名稱，例如 'rawInfo.content'、'content'、"
                "'doc_text'；未提供時使用 SRA_REFERENCE_TEXT_FIELD（預設 rawInfo.content）。"
            ),
            "nullable": True,
        },
    }

    output_type = "any"

    def __init__(self) -> None:
        super().__init__()
        self._es = None

    @property
    def es(self):
        if self._es is None:
            self._es = get_es()
        return self._es

    def forward(
        self,
        uuid: str,
        index_hint: Optional[str] = None,
        text_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not uuid:
            return {"uuid": "", "index": "", "full_text": "", "source": {}, "error": "uuid is required"}

        resolved = resolve_index(index_hint)
        #indexes = split_indexes(resolved) or ([str(resolved)] if resolved else [])
        indexes = split_indexes(resolved)
        # 防呆：若真的還是空，就退回用原 resolved（避免 _resolve_es_index 回傳奇怪值）
        if not indexes and resolved:
            indexes = [str(resolved)]

        dbg("[es_fetch_doc_by_id] indexes =", indexes, "uuid =", uuid)

        src = None
        hit_index = None

        # 1) 逐一 GET（GET 只能單一 index）
        for idx in indexes:
            try:
                resp = self.es.get(index=idx, id=uuid, _source=True)
                if resp and resp.get("found"):
                    src = resp.get("_source") or {}
                    hit_index = resp.get("_index") or idx
                    break
            except NotFoundError:
                continue
            except Exception as e:
                print(f"[ESFetchDocById] get(index={idx!r}, id=uuid) error: {e}")
                continue

        # 2) fallback：跨多 index search(term uuid)
        if src is None:
            try:
                search_index = ",".join(indexes) if indexes else str(resolved)
                resp = self.es.search(
                    index=search_index,
                    size=1,
                    query={"term": {"uuid": uuid}},  # 不用 uuid.keyword，避免 mapping 不一致
                    _source=True,
                )
                hits = (resp.get("hits") or {}).get("hits") or []
                if hits:
                    hit = hits[0]
                    src = hit.get("_source") or {}
                    hit_index = hit.get("_index") or (indexes[0] if indexes else str(resolved))
            except Exception as e:
                print(f"[ESFetchDocById] search(uuid) error: {e}")
                return {
                    "uuid": uuid,
                    "index": ",".join(indexes) if indexes else str(resolved),
                    "full_text": "",
                    "source": {},
                    "error": str(e),
                }

        # 3) 沒資料就回空
        if not src:
            #return {"uuid": uuid, "index": ",".join(indexes) if indexes else str(resolved), "full_text": "", "source": {}}
            return {
                "uuid": uuid,
                "index": ",".join(indexes) if indexes else str(resolved),
                "full_text": "",
                "source": {},
            }
        # 4) 取內文（支援 dot path）
        tf = text_field or get_reference_text_field()
        full_text = get_reference_text(src, field=tf)

        # Preserve the historical root-field fallbacks only for the default
        # contract. An explicitly configured replacement is authoritative and
        # must not silently fall back to a different, potentially noisy source.
        if not full_text and tf == "rawInfo.content":
            full_text = src.get("content") or src.get("doc_text") or ""

        if not isinstance(full_text, str):
            full_text = str(full_text)

        return {
            "uuid": uuid,
            "index": hit_index or (",".join(indexes) if indexes else str(resolved)),
            "full_text": full_text,
            "source": src,
        }
