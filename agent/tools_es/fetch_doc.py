# agent/tools_es/fetch_doc.py
from __future__ import annotations

from typing import Any, Dict, Optional

from elasticsearch import NotFoundError
from smolagents import Tool

from agent.es.es_client import get_es, safe_search as _safe_es_search

from .common import resolve_index, split_indexes, dot_get, dbg


def _as_dict(value: Any) -> Dict[str, Any]:
    """Normalize Elasticsearch client responses to a plain dict."""
    if isinstance(value, dict):
        return value
    body = getattr(value, "body", None)
    if isinstance(body, dict):
        return body
    return {}


class ESFetchDocById(Tool):
    """
    依 uuid 從 Elasticsearch 撈出「單篇完整文件」，主要提供風格學習 / 公文範例用。

    - 預期 index 內有欄位 uuid（或 _id 就是 uuid）
    - 內文欄位預設用 text_field 指定，預設抓 rawInfo.content
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
                "'doc_text'；預設為 'rawInfo.content'。"
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
        text_field: Optional[str] = "rawInfo.content",
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
                resp = _as_dict(self.es.get(index=idx, id=uuid, _source=True))
                # Elasticsearch 8.x get() responses may omit a truthy ``found`` when
                # a document is found, and the local mock client returns only
                # _index/_id/_source. Treat a non-empty _source as a successful hit.
                if resp and (resp.get("found") is not False) and isinstance(resp.get("_source"), dict):
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
                resp = _safe_es_search(
                    {
                        "size": 1,
                        "query": {"term": {"uuid": uuid}},  # 不用 uuid.keyword，避免 mapping 不一致
                        "_source": True,
                    },
                    index=search_index,
                )
                hits_obj = (resp.get("hits") or {}) if isinstance(resp, dict) else {}
                hits = hits_obj.get("hits") if isinstance(hits_obj, dict) else []
                if hits:
                    hit = hits[0]
                    if isinstance(hit, dict):
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
        tf = text_field or "rawInfo.content"
        full_text = (
            dot_get(src, tf)
            or dot_get(src, "rawInfo.content")
            or src.get("content")
            or src.get("doc_text")
            or ""
        )

        if not isinstance(full_text, str):
            full_text = str(full_text)

        return {
            "uuid": uuid,
            "index": hit_index or (",".join(indexes) if indexes else str(resolved)),
            "full_text": full_text,
            "source": src,
        }
