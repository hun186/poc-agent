"""Offline verification of SRAF opt-in GLM TEXT field mapping prerequisites.

Takes ONE operator-saved, owner-only ES GET /<index>/_mapping JSON file.
Does not connect to ES, authenticate, access tokens, write Mapping or modify
retrieval configuration. No user-provided value is reflected in output.
"""
from __future__ import annotations

import json
import os
import stat
import sys

MAX_BYTES = 2 * 1024 * 1024
MAX_INDEX_NAME = 256

# These are the ONLY extra fields used by structured_intent_fields.py:
# every path is a TEXT field under declared nested parents.
TEXT_FIELDS = {
    "Event_Summary": ("multidim_event_json", "Event_Summary"),
    "Event.consequence": ("multidim_event_json", "Event", "consequence"),
    "Event.relation": ("multidim_event_json", "Event", "relation"),
    "Person.action": ("multidim_event_json", "Person", "action"),
    "Person.relation": ("multidim_event_json", "Person", "relation"),
    "Impact.impact_description":
        ("multidim_event_json", "Impact", "impact_description"),
}
NESTED_PATHS = {
    "multidim_event_json": ("multidim_event_json",),
    "multidim_event_json.Event": ("multidim_event_json", "Event"),
    "multidim_event_json.Person": ("multidim_event_json", "Person"),
    "multidim_event_json.Impact": ("multidim_event_json", "Impact"),
}


def _reject_duplicate_keys(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("duplicate_json_key")
        record[key] = value
    return record


def _load_private(path: str) -> dict:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077 or not 0 < meta.st_size <= MAX_BYTES):
            raise ValueError("mapping_input_untrusted")
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as src:
            data = json.load(src, object_pairs_hook=_reject_duplicate_keys)
    finally:
        os.close(fd)
    if not isinstance(data, dict) or len(data) != 1:
        raise ValueError("mapping_index_ambiguous")
    index_name, node = next(iter(data.items()))
    if (not isinstance(index_name, str) or not 0 < len(index_name) <= MAX_INDEX_NAME
            or not isinstance(node, dict)
            or not isinstance(node.get("mappings"), dict)):
        raise ValueError("mapping_shape_invalid")
    return node["mappings"]


def _node(properties: dict, path: tuple[str, ...]) -> dict | None:
    current = properties
    for seg in path:
        if not isinstance(current, dict):
            return None
        v = current.get(seg)
        if not isinstance(v, dict):
            return None
        if seg != path[-1]:
            current = v.get("properties")
        else:
            return v
    return None


def inspect(mapping: dict) -> dict:
    """Returns fixed count/status only, never a private index or ES field value."""
    props = mapping.get("properties")
    if not isinstance(props, dict):
        raise ValueError("mapping_missing_properties")
    mismatched_nested = []
    missing_nested = []
    for key, path in NESTED_PATHS.items():
        node = _node(props, path)
        if node is None:
            missing_nested.append(key)
        elif node.get("type") != "nested" or not isinstance(node.get("properties"), dict):
            mismatched_nested.append(key)

    missing_text = []
    wrong_type = []
    for key, path in TEXT_FIELDS.items():
        node = _node(props, path)
        if node is None:
            missing_text.append(key)
        elif node.get("type") != "text":
            wrong_type.append(key)
    ready = not (
        mismatched_nested or missing_nested or missing_text or wrong_type
    )
    return {
        "schema": "sraf_glm_structured_field_mapping_preflight_v1",
        "scope": "one_private_mapping_snapshot_not_live_identity_verified",
        "result": "PASS_COMPATIBLE" if ready else "NOT_READY",
        "structured_text_on_ab_ready": ready,
        "nested_verified": len(NESTED_PATHS) - len(missing_nested) -
            len(mismatched_nested),
        "nested_expected": len(NESTED_PATHS),
        "text_verified": len(TEXT_FIELDS) - len(missing_text) - len(wrong_type),
        "text_expected": len(TEXT_FIELDS),
        "nested_missing_count": len(missing_nested),
        "nested_type_mismatch_count": len(mismatched_nested),
        "text_missing_count": len(missing_text),
        "text_type_mismatch_count": len(wrong_type),
        # These field names are constant code-defined contract names.
        "missing_field_contracts": sorted(missing_nested + missing_text),
        "mismatched_field_contracts": sorted(mismatched_nested + wrong_type),
        "live_es_identity": "NOT_ATTESTED_BY_TOOL",
        "chinese_analyzer_quality": "NOT_VERIFIED",
        "date_event_id_evidence": "NOT_TESTED",
        "search_recall_quality": "NOT_TESTED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("SRAF_GLM_MAPPING=INCOMPLETE reason=private_mapping_required")
        return 2
    try:
        output = inspect(_load_private(argv[1]))
    except Exception:
        print("SRAF_GLM_MAPPING=INCOMPLETE reason=unsafe_or_invalid_mapping_snapshot")
        return 2
    print("SRAF_GLM_MAPPING=" + json.dumps(
        output, ensure_ascii=True, separators=(",", ":"),
    ))
    return 0 if output["structured_text_on_ab_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
