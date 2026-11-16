"""Private, offline pairwise GLM ES-field A/B with canonical Evidence validation.

Reads two existing ES snapshots. DOES NOT issue ES/SQL/LLM/API requests,
touch production indices, export source content or claim human relevance.
A second ES query must be separately authorized and performed by operator.
This tool does not imply the queries were run or the index Mapping matched.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import copy
import json
import logging
import os
import sys
from typing import Iterator

from agent.es.evidence_core.builder import build_hits_and_evidence
from tools.sraf_topic_adaptive_ab_offline import _private_read

_MATCH_KEYS = ("original_question", "date_from", "date_to",
               "term_groups", "effective_terms", "query_for_snippet")
_OFFLINE_FLAGS = (
    "SRAF_TOPIC_MATCH_ADAPTIVE", "SRAF_EVIDENCE_TRACE",
    "SRAF_EVIDENCE_RESCUE", "SRAF_EVIDENCE_SOURCE_REFILL",
    "SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",
    "SRAF_EVIDENCE_VALID_FAIR_BUDGET",
)


@contextmanager
def _fixed_parser_environment() -> Iterator[None]:
    """Both snapshots use identical canonical, old-style strict parser rules.

    No token/LLM cost, no adaptive admission, no budget clipping; this is a
    one-slice parser A/B, NOT end-to-end report precision.
    """
    before = {key: os.environ.get(key) for key in _OFFLINE_FLAGS}
    old_log_level = logging.root.manager.disable
    try:
        for key in _OFFLINE_FLAGS:
            os.environ.pop(key, None)
        # Prevent private input fields showing in third-party parser logs.
        logging.disable(logging.CRITICAL)
        yield
    finally:
        logging.disable(old_log_level)
        for key, old in before.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _identity(hit: dict) -> tuple[str, str]:
    idx, docid = hit.get("_index"), hit.get("_id")
    if (not isinstance(idx, str) or not 0 < len(idx) <= 256 or
            not isinstance(docid, str) or not 0 < len(docid) <= 256):
        raise ValueError("es_hit_identity_missing")
    return idx, docid


def _prepare(data: dict, expected_role: str) -> tuple[dict, list[tuple[str, str]]]:
    if data.get("snapshot_role") != expected_role:
        raise ValueError("snapshot_role_invalid")
    hits = data["es_hits"]  # basic bounds/types already checked by _private_read
    source_keys = [_identity(h) for h in hits]
    if len(set(source_keys)) != len(source_keys):
        raise ValueError("duplicate_es_hit_identity")
    # Snapshot metadata must not be used as Evidence or reported to stdout.
    return data, source_keys


def _parse(data: dict, keys: list[tuple[str, str]]) -> dict:
    # Different ES score/rank order is permitted. Exact source identity is
    # (index,id), never user metadata UUID, title or event_id.
    _, evidence, _ = build_hits_and_evidence(
        copy.deepcopy(data["es_hits"]),
        date_from=data.get("date_from"),
        date_to=data.get("date_to"),
        allowed_years=None,
        term_groups=[set(g) for g in data["term_groups"]],
        effective_terms=data["effective_terms"],
        query_for_snippet=data.get("query_for_snippet") or "",
        original_question=data["original_question"],
        include_source_hit_ordinal=True,
    )
    valid_sources: set[tuple[str, str]] = set()
    strong_sources: set[tuple[str, str]] = set()
    policies: Counter[str] = Counter()
    for item in evidence:
        ordinal = item.get("__sraf_source_hit_ordinal")
        if type(ordinal) is not int or not 0 <= ordinal < len(keys):
            raise ValueError("evidence_source_provenance_invalid")
        source = keys[ordinal]
        policy = item.get("match_policy")
        scope = item.get("match_scope")
        # A legacy any-effective-term fallback can retain match_policy
        # 'strict' despite having ZERO Topic Match axes. It is a parser
        # output, but never claim it as a date+topic-accepted Evidence.
        if scope == "fallback_any_term":
            policies["fallback_any_term"] += 1
            continue
        if policy not in ("strict", "relaxed", "adaptive_two_axis"):
            raise ValueError("unknown_evidence_match_policy")
        valid_sources.add(source)
        if not item.get("weak_evidence"):
            strong_sources.add(source)
        policies[policy] += 1
    return {
        "valid_sources": valid_sources, "strong_sources": strong_sources,
        # Distinguish total parser output from snippets that actually
        # passed a Topic Match group threshold (strict or relaxed).
        "parser_output": len(evidence),
        "evidence": sum(policies[p] for p in (
            "strict", "relaxed", "adaptive_two_axis"
        )),
        "strong": sum(not row.get("weak_evidence") and
                      row.get("match_scope") != "fallback_any_term"
                      for row in evidence),
        "weak": sum(bool(row.get("weak_evidence")) and
                    row.get("match_scope") != "fallback_any_term"
                    for row in evidence),
        "policies": policies,
    }


def compare_pair(base: dict, enhanced: dict) -> dict:
    """Metrics are parser eligibility, not assessed semantic relevance."""
    a, a_keys = _prepare(base, "baseline")
    b, b_keys = _prepare(enhanced, "structured_on")
    for field in _MATCH_KEYS:
        if a.get(field) != b.get(field):
            raise ValueError("case_parameters_mismatch")
    # Equal input parameters are necessary, not proof that the same ES index
    # alias/date filters/PIT were used. That needs external operator attestation.
    with _fixed_parser_environment():
        left = _parse(a, a_keys)
        right = _parse(b, b_keys)
    a_docs, b_docs = set(a_keys), set(b_keys)
    additional_docs = b_docs - a_docs
    new_valid = right["valid_sources"] - left["valid_sources"]
    lost_valid = left["valid_sources"] - right["valid_sources"]
    new_strong = right["strong_sources"] - left["strong_sources"]
    new_docs_with_valid = additional_docs & right["valid_sources"]
    # Count candidate change and Evidence quality SEPARATELY.
    return {
        "schema": "sraf_structured_field_pair_ab_v1",
        "scope": "two_private_operator_snapshots_one_parser_not_live_es_or_report",
        "comparison": "baseline_vs_structured_on_unverified_capture_labels",
        "baseline_candidates": len(a_docs),
        "enhanced_candidates": len(b_docs),
        "candidate_new_sources": len(additional_docs),
        "candidate_lost_sources": len(a_docs - b_docs),
        "baseline_parser_output_evidence": left["parser_output"],
        "enhanced_parser_output_evidence": right["parser_output"],
        "baseline_any_term_fallback_evidence": left["policies"]["fallback_any_term"],
        "enhanced_any_term_fallback_evidence": right["policies"]["fallback_any_term"],
        "baseline_date_topic_valid_evidence": left["evidence"],
        "enhanced_date_topic_valid_evidence": right["evidence"],
        "baseline_strong_evidence": left["strong"],
        "enhanced_strong_evidence": right["strong"],
        "baseline_weak_evidence": left["weak"],
        "enhanced_weak_evidence": right["weak"],
        "baseline_valid_sources": len(left["valid_sources"]),
        "enhanced_valid_sources": len(right["valid_sources"]),
        "valid_sources_gained": len(new_valid),
        "valid_sources_lost": len(lost_valid),
        "strong_sources_gained": len(new_strong),
        "new_candidate_sources_with_valid_evidence": len(new_docs_with_valid),
        "new_candidate_sources_without_valid_evidence":
            len(additional_docs - new_docs_with_valid),
        "baseline_strict_evidence": left["policies"]["strict"],
        "enhanced_strict_evidence": right["policies"]["strict"],
        "human_precision_assessment": "REQUIRED",
        "same_es_index_mapping_verified": "NOT_TESTED",
        "query_elapsed_and_token_cost": "NOT_MEASURED",
        "live_es_query": "NOT_RUN_BY_TOOL",
        "report_docx": "NOT_TESTED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("SRAF_STRUCTURED_AB=INCOMPLETE reason=two_private_snapshots_required")
        return 2
    try:
        metrics = compare_pair(
            _private_read(argv[1], allow_empty_hits=True),
            _private_read(argv[2], allow_empty_hits=True),
        )
    except Exception:
        # No traceback, path, ES ID, question, date or source content.
        print("SRAF_STRUCTURED_AB=INCOMPLETE reason=invalid_or_unmatched_private_snapshots")
        return 2
    print("SRAF_STRUCTURED_AB=" + json.dumps(
        metrics, ensure_ascii=True, separators=(",", ":"),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
