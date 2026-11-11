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
# SQS negation across separately-scoped nested clauses is NOT document-global.
# Account for documented +-term, parens and OR operator-adjacent exclusions.
# Keep the legacy single-query behavior for signed exclusion expressions.
_DOCUMENT_NEGATION = re.compile(r"(?:^|[\s(+|])-(?=\S)")


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


def _nested_parents(path: str, metadata: dict[str, dict[str, Any]]) -> list[str]:
    """Return outer-to-inner nested ancestors; both levels must be entered."""
    parts = path.split(".")
    parents = (".".join(parts[:i]) for i in range(1, len(parts)))
    return [p for p in parents if metadata.get(p, {}).get("type") == "nested"]


def _wrap_nested(path: str, clause: dict[str, Any],
                 metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for parent in reversed(_nested_parents(path, metadata)):
        clause = {"nested": {"path": parent, "query": clause, "score_mode": "max"}}
    return clause


def _grouped_query(
    clauses: list[tuple[str, dict[str, Any]]],
    metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [_wrap_nested(path, clause, metadata) for path, clause in clauses]


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
    if _DOCUMENT_NEGATION.search(term):
        # Each nested OR branch evaluates its own -excluded term and can admit
        # a root document excluded by another branch. A cross-context parser
        # would be required to preserve every SQS Boolean expression. Use the
        # exact legacy single-context form rather than invent different
        # document-level negation semantics; no substring OR can bypass it.
        legacy_fields = [f for f in search_fields
                         if isinstance(f, str) and _field_spec(f) is not None]
        warnings.append(
            "含排除詞的進階查詢維持既有全文模式，避免跨 nested 欄位繞過排除條件；"
            "這類查詢暫不支援部分字串補查。"
        )
        if not legacy_fields:
            return {"match_none": {}}, warnings
        return {"simple_query_string": {
            "query": term, "fields": legacy_fields, "default_operator": "and",
        }}, warnings
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
        nested_parents = _nested_parents(path, metadata) if mapping_ok else []
        parent = nested_parents[-1] if nested_parents else None
        field = path + (f"^{weight:g}" if weight != 1 else "")
        groups[parent].append(field)
        eligible.append((path, weight))

    should: list[dict[str, Any]] = []
    for nested_path, fields in groups.items():
        clause = {"simple_query_string": {
            "query": term, "fields": fields, "default_operator": "and",
        }}
        if nested_path is not None:
            # A nested child within a nested parent needs BOTH query contexts.
            first_field = fields[0].split("^", 1)[0]
            clause = _wrap_nested(first_field, clause, metadata)
        should.append(clause)

    contains = mode == "contains" or (mode == "auto" and "_" in term)
    if contains:
        if not 4 <= len(term) <= 64 or _LITERAL.fullmatch(term) is None:
            warnings.append("包含字串模式僅支援 4～64 個字元的單一文字／數字／底線字串；此次只使用一般全文搜尋。")
        elif not mapping_ok:
            warnings.append("Mapping 無法取得，不能安全判定 keyword 欄位；此次無法保證包含字串搜尋。")
        else:
            contain_clauses: list[tuple[str, dict[str, Any]]] = []
            seen_exact: set[str] = set()
            for path, weight in eligible:
                # Configured title.keyword is a real searchable field: its
                # allowed parent is title, rather than an arbitrary wildcard
                # path. Never enable substring on unreviewed custom fields.
                base_path = path[:-len(".keyword")] if path.endswith(".keyword") else path
                if base_path not in _CONTAINS_FIELDS or len(contain_clauses) >= _MAX_CONTAINS_FIELDS:
                    continue
                meta = metadata.get(path, {})
                exact_path: str | None = None
                if meta.get("type") in _EXACT_TYPES:
                    exact_path = path
                elif meta.get("type") in {"text", "match_only_text"} and "keyword" in meta.get("fields", []):
                    exact_path = f"{path}.keyword"
                if exact_path and exact_path not in seen_exact:
                    seen_exact.add(exact_path)
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
