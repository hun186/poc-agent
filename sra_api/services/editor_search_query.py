"""Mapping-aware, bounded editor search query construction (no index writes)."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_TEXT_TYPES = {"text", "match_only_text", "keyword", "constant_keyword", "wildcard"}
_EXACT_TYPES = {"keyword", "constant_keyword", "wildcard"}
# Never run leading-wildcard scans over whole article bodies or arbitrary config paths.
_CONTAINS_FIELDS = {
    "title", "subject", "uuid", "rawInfo.title",
    "communication.subject", "multidim_event_json.article_title",
}
_MAX_CONTAINS_FIELDS = 6
_LITERAL = re.compile(r"[\w-]+", re.UNICODE)


def _field_spec(field: str) -> tuple[str, float] | None:
    path, separator, boost = field.partition("^")
    if not path or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", path):
        return None
    if not separator:
        return path, 1.0
    try:
        weight = float(boost)
    except (ValueError, OverflowError):
        return None
    if not (0 < weight <= 10):
        return None
    return path, weight


def _nested_parent(path: str, metadata: dict[str, dict[str, Any]]) -> str | None:
    parts = path.split(".")
    parents = (".".join(parts[:i]) for i in range(1, len(parts)))
    nested = [p for p in parents if metadata.get(p, {}).get("type") == "nested"]
    return nested[-1] if nested else None


def _grouped_query(
    clauses: list[tuple[str, dict[str, Any]]],
    metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for path, clause in clauses:
        parent = _nested_parent(path, metadata)
        if parent:
            out.append({"nested": {"path": parent, "query": clause, "score_mode": "max"}})
        else:
            out.append(clause)
    return out


def build_editor_search_query(
    text: str,
    search_fields: list[str],
    metadata: dict[str, dict[str, Any]],
    mapping_ok: bool,
    mode: str = "auto",
) -> tuple[dict[str, Any], list[str]]:
    """Search all configured fields; use bounded keyword substring only when safe.

    Automatic mode augments standard text matching only for a literal token
    containing an underscore. Explicit contains mode permits other literals.
    No arbitrary leading-wildcard query is accepted from the client.
    """
    if mode not in {"auto", "text", "contains"}:
        raise ValueError("invalid_search_mode")
    term = text.strip()
    if not term:
        return {"match_all": {}}, []

    warnings: list[str] = []
    groups: dict[str | None, list[str]] = defaultdict(list)
    eligible: list[tuple[str, float]] = []
    for raw in search_fields:
        if not isinstance(raw, str):
            continue
        spec = _field_spec(raw)
        if spec is None:
            continue
        path, weight = spec
        if mapping_ok and metadata.get(path, {}).get("type") not in _TEXT_TYPES:
            continue
        parent = _nested_parent(path, metadata) if mapping_ok else None
        field = path + (f"^{weight:g}" if weight != 1 else "")
        groups[parent].append(field)
        eligible.append((path, weight))

    should: list[dict[str, Any]] = []
    for nested_path, fields in groups.items():
        clause = {"simple_query_string": {
            "query": term, "fields": fields, "default_operator": "and",
        }}
        if nested_path is not None:
            clause = {"nested": {
                "path": nested_path, "query": clause, "score_mode": "max",
            }}
        should.append(clause)

    contains = mode == "contains" or (mode == "auto" and "_" in term)
    if contains:
        if not 4 <= len(term) <= 64 or _LITERAL.fullmatch(term) is None:
            warnings.append("包含字串模式僅支援 4～64 個字元的單一文字／數字／底線字串；此次只使用一般全文搜尋。")
        elif not mapping_ok:
            warnings.append("Mapping 無法取得，不能安全判定 keyword 欄位；此次無法保證包含字串搜尋。")
        else:
            contain_clauses: list[tuple[str, dict[str, Any]]] = []
            for path, weight in eligible:
                if path not in _CONTAINS_FIELDS or len(contain_clauses) >= _MAX_CONTAINS_FIELDS:
                    continue
                meta = metadata.get(path, {})
                exact_path: str | None = None
                if meta.get("type") in _EXACT_TYPES:
                    exact_path = path
                elif meta.get("type") in {"text", "match_only_text"} and "keyword" in meta.get("fields", []):
                    exact_path = f"{path}.keyword"
                if exact_path:
                    contain_clauses.append((path, {"wildcard": {exact_path: {
                        "value": f"*{term}*", "case_insensitive": True,
                        "boost": weight,
                    }}}))
            if contain_clauses:
                should.extend(_grouped_query(contain_clauses, metadata))
                warnings.append(
                    "已對最多 6 個標題／主旨／UUID keyword 欄位增加包含字串查詢；"
                    "可能較慢，未涵蓋未建立 keyword 子欄位的內容。"
                )
            else:
                warnings.append(
                    "此 index 的標題／主旨／UUID 沒有可用的 keyword 或 wildcard 欄位；"
                    "包含字串可能無法命中，請檢查 Mapping。"
                )

    if not should:
        warnings.append("Index Mapping 中沒有可用的已設定搜尋欄位。")
        return {"match_none": {}}, warnings
    if len(should) == 1:
        return should[0], warnings
    return {"bool": {"should": should, "minimum_should_match": 1}}, warnings
