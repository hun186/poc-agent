"""Deterministic, privacy-minimizing source-label consistency checker.

The report LLM may print labels like 來源1 or 來源1、2. Check labels only
against evidence ref_no values supplied to that very report call. This cannot
validate factual claims or semantic support and never edits evidence or IDs.
"""
from __future__ import annotations

import re
from itertools import islice
from typing import Any, Iterable

AUDIT_SCHEMA = "sraf_report_citation_labels_v1"
MAX_TEXT_CHARS = 200_000
MAX_REFS = 500
MAX_LABELS = 10_000
# Colon-delimited '資料來源：2026...' is not an Evidence reference.
# Each part after 來源 must be a small numbered citation, not a date/name.
_SOURCE_LABEL = re.compile(
    r"(?<![A-Za-z0-9_])來源[ \t]*"
    r"([0-9]+(?:[、，,/][ \\t]*[0-9]+)*)"
)
_LABEL_PART = re.compile(r"[、，,/][ \t]*")


def audit_report_citation_labels(
    report: Any, allowed_refs: Iterable[Any],
) -> dict[str, Any]:
    """Return only fixed status and numeric counts, never model text or IDs.

    A label audit does NOT prove that any cited sentence is supported by the
    evidence; it only catches citations to nonexistent ref_no values.
    """
    result = {
        "schema": AUDIT_SCHEMA, "status": "invalid_contract",
        "labels_seen": 0, "unique_labels": 0, "unmapped_labels": 0,
        "allowed_reference_count": 0,
    }
    if not isinstance(report, str) or len(report) > MAX_TEXT_CHARS:
        return result
    try:
        # Never materialize an unbounded or malicious source iterable.
        candidates = list(islice(iter(allowed_refs), MAX_REFS + 1))
    except (TypeError, ValueError):
        return result
    if len(candidates) > MAX_REFS or any(
        type(ref) is not int or not 0 < ref <= 1_000_000 for ref in candidates
    ):
        return result
    permitted = set(candidates)
    if len(permitted) != len(candidates):
        return result
    result["allowed_reference_count"] = len(permitted)
    labels: list[int] = []
    for match in _SOURCE_LABEL.finditer(report):
        parts = _LABEL_PART.split(match.group(1))
        if (len(labels) + len(parts) > MAX_LABELS
                or any(len(part) > 6 for part in parts)):
            # A long list must never be silently accepted as a valid prefix:
            # return incomplete rather than truncate and miss phantom IDs.
            result["status"] = "limit_exceeded"
            return result
        labels.extend(int(part) for part in parts)
    unique = set(labels)
    result.update(
        labels_seen=len(labels), unique_labels=len(unique),
        unmapped_labels=len(unique - permitted),
        status=("unmapped" if unique - permitted else
                "no_labels" if not labels else "labels_match"),
    )
    return result


def citation_integrity_notice(audit: dict[str, Any]) -> str | None:
    """A conservative warning to prepend, not a forged or altered citation."""
    status = audit.get("status")
    if status == "unmapped":
        return (
            "⚠️ 引用編號核對提醒：報告出現無法對應本次有效 Evidence 的來源編號。"
            "該段引用可能不可靠；請核對原文與來源，勿直接用於正式結論。"
        )
    if status == "no_labels" and audit.get("allowed_reference_count", 0) > 0:
        return (
            "⚠️ 引用完整性提醒：報告未標示可對應本次 Evidence 的來源編號；"
            "本層無法確認各項具體敘述的依據，請檢查原始來源。"
        )
    if status in ("invalid_contract", "limit_exceeded"):
        return "⚠️ 引用編號核對未完成；請人工檢查報告與來源。"
    return None
