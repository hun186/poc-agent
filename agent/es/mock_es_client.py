from __future__ import annotations

import copy
import time
from typing import Any

MOCK_INDEX = "vercel_mock_vessel_activities"
_NOW = "2026-06-22T00:00:00Z"

MOCK_DOCS: dict[str, dict[str, dict[str, Any]]] = {
    MOCK_INDEX: {
        "mock-001": {
            "uuid": "mock-001",
            "title": "Vercel 測試資料：漁船活動通報",
            "subject": "疑似越界作業通報",
            "content": "這是 Vercel mock 資料庫中的示範文件，用於無法連線 Elasticsearch 時檢閱搜尋與編修流程。",
            "importDT": "2026-06-20T08:15:00Z",
            "rawInfo": {"title": "漁船活動通報", "date": "2026-06-20"},
        },
        "mock-002": {
            "uuid": "mock-002",
            "title": "Vercel 測試資料：港口查驗紀錄",
            "subject": "港口查驗與補給紀錄",
            "content": "示範 Excel 匯入後可供檢閱的港口查驗紀錄。",
            "importDT": "2026-06-19T12:30:00Z",
            "rawInfo": {"title": "港口查驗紀錄", "date": "2026-06-19"},
        },
    }
}

MAPPING = {
    MOCK_INDEX: {
        "mappings": {
            "properties": {
                "uuid": {"type": "keyword"},
                "title": {"type": "text"},
                "subject": {"type": "text"},
                "content": {"type": "text"},
                "importDT": {"type": "date"},
                "rawInfo": {"properties": {"title": {"type": "text"}, "date": {"type": "keyword"}}},
            }
        }
    }
}


class MockIndicesClient:
    def __init__(self, parent: "MockElasticsearch") -> None:
        self._parent = parent

    def exists(self, index: str) -> bool:
        return index in self._parent.docs

    def get_alias(self, index: str = "*") -> dict[str, Any]:
        return {name: {"aliases": {}} for name in self._parent.docs}

    def get_mapping(self, index: str) -> dict[str, Any]:
        if index not in self._parent.docs:
            return {}
        return copy.deepcopy(MAPPING.get(index, {"mappings": {"properties": {}}}))


class MockElasticsearch:
    is_sra_mock = True

    def __init__(self) -> None:
        self.docs = copy.deepcopy(MOCK_DOCS)
        self.indices = MockIndicesClient(self)

    def ping(self) -> bool:
        return True

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        docs = self.docs.get(index, {})
        query_text = _extract_query_text(body).lower()
        rows = []
        for doc_id, source in docs.items():
            haystack = " ".join(str(v) for v in _flatten_values(source)).lower()
            if query_text and query_text not in haystack:
                continue
            rows.append({"_id": doc_id, "_index": index, "_score": 1.0, "_source": copy.deepcopy(source)})
        rows.sort(key=lambda hit: str(hit["_source"].get("importDT") or ""), reverse=True)
        offset = int(body.get("from") or 0)
        size = int(body.get("size") or 20)
        return {"hits": {"total": {"value": len(rows)}, "hits": rows[offset: offset + size]}, "_mock": True}

    def get(self, *, index: str, id: str, _source: bool = True) -> dict[str, Any]:
        if id not in self.docs.get(index, {}):
            raise KeyError(id)
        return {"_index": index, "_id": id, "_source": copy.deepcopy(self.docs[index][id])}

    def index(self, *, index: str, id: str, document: dict[str, Any], refresh: str = "") -> dict[str, Any]:
        bucket = self.docs.setdefault(index, {})
        created = id not in bucket
        bucket[id] = copy.deepcopy(document)
        bucket[id].setdefault("importDT", _NOW)
        return {"_index": index, "_id": id, "result": "created" if created else "updated"}

    def delete(self, *, index: str, id: str, refresh: str = "") -> dict[str, Any]:
        if id not in self.docs.get(index, {}):
            raise KeyError(id)
        del self.docs[index][id]
        return {"_index": index, "_id": id, "result": "deleted"}


def _extract_query_text(body: dict[str, Any]) -> str:
    try:
        must = body.get("query", {}).get("bool", {}).get("must", [])
        for item in must:
            if "simple_query_string" in item:
                return str(item["simple_query_string"].get("query") or "")
    except Exception:
        return ""
    return ""


def _flatten_values(value: Any):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _flatten_values(nested)
    else:
        yield value
