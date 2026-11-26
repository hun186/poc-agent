"""A9 private offline replay of A6 on a frozen first-primary ES response.

The raw response is supplied locally by an operator. No ES/LLM requests,
production mutation, or automatic relaxation. The parser uses an explicit
legacy default EvidenceBuildConfig, not ambient rollout flags. Only complete
bounded parsed slices are evaluated. The fixture does not prove that the
original ES query was correct, or that its returned slice is corpus-complete.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
import os
import time

from .arc_relax_shadow import (
    prepare_low_volume_pilot, _identity, StrictSliceCounts, MAX_HITS, MAX_ROWS,
    MAX_ROWS_PER_HIT, MAX_CHARS, MAX_ROW_CHARS, TARGET_STRICT,
)
from .arc_tighten_shadow import CandidatePressure
from .arc_selection_eval import evaluate_selection_cases
from .arc_acceptance_screen import _valid_policy, screen_selection_acceptance
from .arc_resource_eval import evaluate_resource_cases
from .arc_semantic_eval import MAX_CASES, MAX_TOTAL_ROWS
from .builder import collect_snippets, build_hits_and_evidence
from .parser import parse_es_hits
from .snippet import build_evidence_snippet
from .models import EvidenceBuildConfig
from .question_anchor import derive_explicit_question_anchor
from .cross_language_alias import alias_matches
from ..arc_request_budget import ArcRequestBudget, bind_arc_budget

_MAX_CASE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_KEYS = {"question", "query", "groups", "date_from", "date_to", "response"}
_LABELS = {"relevant", "uncertain", "unrelated"}


@dataclass(frozen=True, repr=False)
class _PreparedCase:
    digest: str = field(repr=False)
    rows: tuple[dict, ...] = field(repr=False)
    observation: dict = field(repr=False)
    pilot_status: str
    pipeline_status: str
    pipeline_resources: dict | None = field(default=None, repr=False)


def _date_window(start, end):
    try:
        return (type(start) is str and type(end) is str
                and date.fromisoformat(start).isoformat() == start
                and date.fromisoformat(end).isoformat() == end and start <= end)
    except ValueError:
        return False


def _pipeline_check(case, groups, pressure, baseline, added, *, measurements=None):
    """Check the real builder and final date-refill selection, without IO.

    The sample is exhausted, so use its returned source count as the
    declared result limit, not a guessed original production request size.
    """
    from agent.es.date_refill import refill_date_filtered_evidence

    response = case["response"]
    raw_hits = response["hits"]["hits"]
    origin = "__sraf_source_hit_ordinal"
    block = "__sraf_block_index"
    expected = [key for key, _ in sorted(baseline.items(), key=lambda item: item[1])]
    candidate = expected + [key for key, _ in sorted(added.items(), key=lambda item: item[1])]

    def run(pilot):
        status = {}
        captured = []
        budget = ArcRequestBudget()
        def build(hits):
            result = build_hits_and_evidence(
                hits, date_from=case["date_from"], date_to=case["date_to"],
                effective_terms=list(dict.fromkeys(t for g in case["groups"] for t in g)),
                term_groups=groups, query_for_snippet=case["query"],
                original_question=case["question"], include_source_hit_ordinal=True,
                config=EvidenceBuildConfig(), arc_candidate_pressure=pressure if pilot else None,
                _offline_a6_pilot=pilot, _offline_a6_status=status)
            captured.append(result)
            return result
        def no_next(_):
            raise ValueError("unexpected_refill")
        try:
            with bind_arc_budget((budget, 1)):
                final_hits, final_rows, _, meta = refill_date_filtered_evidence(
                    body={"size": len(raw_hits)}, first_response=response,
                    requested_size=len(raw_hits), search_next=no_next,
                    build_evidence=build)
        finally:
            budget.seal()
        if len(captured) != 1 or meta["pages_fetched"] != 1:
            return None, "unexpected_refill"
        hits, evidence, _ = captured[0]
        if (final_hits != [{k:v for k,v in row.items() if k != origin} for row in hits]
                or final_rows != [{k:v for k,v in row.items() if k != origin} for row in evidence]):
            return None, "final_selection_changed"
        if pilot and status.get("status") != "pilot_candidate_prepared":
            return None, "pilot_builder_declined"
        return evidence, "prepared"

    def identities(evidence):
        return [(row[origin], row.get(block), row["text"], tuple(row.get("event_ids", [])))
                for row in evidence]

    def run_measured(pilot):
        if measurements is None:
            return run(pilot)
        arm = "candidate" if pilot else "baseline"
        record = {"status": "failed", "elapsed_ms": None, "es_calls": 0,
                  "llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        measurements[arm] = record
        started = time.monotonic_ns()
        try:
            result, why = run(pilot)
            if result is not None:
                record["status"] = "completed"
            return result, why
        finally:
            record["elapsed_ms"] = (time.monotonic_ns() - started) // 1000000

    try:
        first, why = run_measured(False)
        if first is None or identities(first) != expected:
            if measurements is not None:
                measurements["baseline"]["status"] = "failed"
            return "baseline_pipeline_mismatch"
        second, why = run_measured(True)
        if second is None:
            return why
        if (identities(second) != candidate or second[:len(first)] != first
                or any(row.get("match_policy") != "adaptive_two_axis"
                       or row.get("weak_evidence") is not True
                       or row.get("match_scope") != "text"
                       or row.get("group_hits") != 2
                       or row.get("structured_time_context") is not True
                       or not row.get("matched_event_time_candidates")
                       for row in second[len(first):])):
            if measurements is not None:
                measurements["candidate"]["status"] = "failed"
            return "candidate_pipeline_mismatch"
        return "pipeline_parity"
    except Exception:
        # A failed optional integration check cannot certify compatibility
        # or discard the independently valid strict-only counterfactual.
        return "pipeline_unavailable"


def _prepare(case, *, check_pipeline=False, measure_pipeline=False):
    if type(case) is not dict or set(case) != _KEYS:
        return None
    # This API is for local JSON-native inputs. Bound the encoded fixture
    # before parsing raw sources or expanding structured evidence.
    raw = json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if not 0 < len(raw) <= _MAX_CASE_BYTES:
        return None
    q, query, groups = case["question"], case["query"], case["groups"]
    start, end, response = case["date_from"], case["date_to"], case["response"]
    if (type(q) is not str or not 0 < len(q) <= 8192
            or type(query) is not str or not 0 < len(query) <= 2048
            or not _date_window(start, end)
            or type(groups) is not list or not 3 <= len(groups) <= 16
            or any(type(g) is not list or not 1 <= len(g) <= 32
                   or any(type(t) is not str or not 0 < len(t) <= 160 or not t.strip() for t in g)
                   or len(set(g)) != len(g) for g in groups)
            or sum(map(len, groups)) > 64):
        return None
    groups = [set(g) for g in groups]
    anchor = derive_explicit_question_anchor(q, groups)
    if anchor is None:
        return None
    pressure = CandidatePressure.from_primary(response)
    if pressure.relation not in ("eq", "gte") or not 1 <= pressure.returned <= MAX_HITS:
        return None
    raw_hits = response["hits"]["hits"]
    source_ids = set()
    for hit in raw_hits:
        if (type(hit) is not dict or type(hit.get("_index")) is not str
                or not 0 < len(hit["_index"]) <= 256
                or type(hit.get("_id")) is not str or not 0 < len(hit["_id"]) <= 256
                or type(hit.get("_source")) is not dict):
            return None
        pair = (hit["_index"], hit["_id"])
        if pair in source_ids:
            return None
        source_ids.add(pair)
    hits, _ = parse_es_hits(raw_hits, query_for_snippet=query, config=EvidenceBuildConfig())
    if (len(hits) != len(raw_hits)
            or any(h.source_hit_ordinal != i or len(h.citations) > MAX_ROWS_PER_HIT
                   for i, h in enumerate(hits))):
        return None
    texts = [c.text for h in hits for c in h.citations]
    if (not 1 <= len(texts) <= MAX_ROWS
            or any(type(t) is not str or not 0 < len(t) <= MAX_ROW_CHARS for t in texts)
            or sum(map(len, texts)) > MAX_CHARS):
        return None
    counts = StrictSliceCounts()
    strict = collect_snippets(hits, date_from=start, date_to=end, term_groups=groups,
                              min_groups_required=None, arc_counts=counts)
    if len(strict) >= TARGET_STRICT:
        return None
    baseline = {_identity(e): i + 1 for i, e in enumerate(strict)}
    if len(baseline) != len(strict):
        return None
    # Rebuild only canonical date-eligible rows. All such rows are labeled,
    # not just the selected additions, so the denominator is explicit.
    universe = []
    seen = set()
    for h in hits:
        for c in h.citations:
            ev = build_evidence_snippet(h, c, date_from=start, date_to=end)
            if ev is None:
                continue
            key = _identity(ev)
            if key in seen:
                return None
            seen.add(key)
            universe.append((key, ev))
    if len(universe) != counts.canonical_eligible or not set(baseline).issubset(seen):
        return None
    budget = ArcRequestBudget()
    try:
        with bind_arc_budget((budget, 1)):
            observation, candidates, pilot_rows, pilot_status = prepare_low_volume_pilot(
                hits, strict, groups, counts=counts, pressure=pressure,
                original_question=q, date_from=start, date_to=end, allowed_years=None,
            )
    finally:
        budget.seal()
    if (observation["status"] != "observed_relaxation"
            or observation["sample_limited"] is not False
            or len(candidates) != observation["hypothetical_add_cap"]
            or len(set(candidates)) != len(candidates)
            or not set(candidates).issubset(seen)
            or set(candidates).intersection(baseline)):
        return None
    added = {key: len(strict) + i for i, key in enumerate(candidates, 1)}
    strong = {_identity(e): not e.weak_evidence for e in strict}
    rows = tuple(
        {"ordinal": i, "source": ev.source_hit_ordinal, "text": ev.text,
         "direct_anchor": alias_matches(anchor.literal, ev.text),
         "strong": strong.get(key, False),
         "baseline_rank": baseline.get(key),
         "candidate_rank": baseline.get(key, added.get(key))}
        for i, (key, ev) in enumerate(universe, 1)
    )
    # Bind annotations to both frozen input and exact parser/order output,
    # not merely to ordinal positions that could drift after a code change.
    digest = sha256(raw + b"\x00" + json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()
    pipeline_status = "not_pilot_eligible"
    measurements = None
    if check_pipeline and pilot_status == "pilot_candidate_prepared":
        if measure_pipeline:
            measurements = {}
            pipeline_status = _pipeline_check(case, groups, pressure, baseline, added,
                                              measurements=measurements)
            for arm in ("baseline", "candidate"):
                if arm not in measurements:
                    measurements[arm] = {"status": "cancelled", "elapsed_ms": None,
                                         "es_calls": 0, "llm_calls": 0,
                                         "prompt_tokens": 0, "completion_tokens": 0}
            if pipeline_status != "pipeline_parity":
                # A parity/validation exception may occur after a builder
                # returned. No failed case can certify a completed pair.
                if all(v["status"] == "completed" for v in measurements.values()):
                    measurements["candidate"]["status"] = "failed"
        else:
            pipeline_status = _pipeline_check(case, groups, pressure, baseline, added)
    return _PreparedCase(digest, rows, observation, pilot_status, pipeline_status, measurements)


def prepare_relax_annotation(case):
    """Private local-only template; contains text, never log or upload it.

    Gold is deliberately null until independently labeled. No actual source
    ID is included. The digest is for pairing, not security or authorization.
    """
    try:
        prepared = _prepare(case)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return None
    if prepared is None:
        return None
    return {"fixture_digest": prepared.digest,
            "rows": [{"ordinal": r["ordinal"], "source": r["source"], "text": r["text"],
                      "gold": None} for r in prepared.rows]}


def replay_relax_cases(cases, *, _acceptance_policy=None):
    """Validate labels and compare strict-only vs first bounded A6 additions."""
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        return None
    paired = []
    pilot_paired = []
    measured_cases = []
    acceptance_pairs = []
    digests = set()
    pilot_status_counts = {}
    pipeline_status_counts = {}
    pipeline_paired = []
    added = total_rows = total_bytes = 0
    for fixture in cases:
        try:
            if type(fixture) is not dict or set(fixture) != {"case", "fixture_digest", "labels"}:
                return None
            total_bytes += len(json.dumps(fixture, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            if total_bytes > _MAX_TOTAL_BYTES:
                return None
            prepared = _prepare(fixture["case"], check_pipeline=True,
                                measure_pipeline=_acceptance_policy is not None)
            labels = fixture["labels"]
            if (prepared is None or fixture["fixture_digest"] != prepared.digest
                    or type(labels) is not list or len(labels) != len(prepared.rows)):
                return None
            if _acceptance_policy is not None:
                if prepared.digest in digests:
                    return None
                digests.add(prepared.digest)
            gold = {}
            for item in labels:
                if (type(item) is not dict
                        or set(item) not in ({"ordinal", "gold"},
                                             {"ordinal", "source", "text", "gold"})
                        or type(item["ordinal"]) is not int
                        or not 1 <= item["ordinal"] <= len(prepared.rows)
                        or item["ordinal"] in gold
                        or type(item["gold"]) is not str or item["gold"] not in _LABELS):
                    return None
                if "text" in item:
                    original = prepared.rows[item["ordinal"] - 1]
                    if (type(item["source"]) is not int
                            or item["source"] != original["source"]
                            or type(item["text"]) is not str
                            or item["text"] != original["text"]):
                        return None
                gold[item["ordinal"]] = item["gold"]
            total_rows += len(prepared.rows)
            if total_rows > MAX_TOTAL_ROWS:
                return None
            case_rows = [{**{k: v for k, v in row.items() if k != "text"},
                          "gold": gold[row["ordinal"]]} for row in prepared.rows]
            paired.append(case_rows)
            pilot_status_counts[prepared.pilot_status] = pilot_status_counts.get(prepared.pilot_status, 0) + 1
            if prepared.pilot_status == "pilot_candidate_prepared":
                pilot_paired.append(case_rows)
            pipeline_status_counts[prepared.pipeline_status] = pipeline_status_counts.get(prepared.pipeline_status, 0) + 1
            if prepared.pipeline_resources is not None:
                measured_cases.append(prepared.pipeline_resources)
            if prepared.pipeline_status == "pipeline_parity":
                pipeline_paired.append(case_rows)
                if _acceptance_policy is not None:
                    acceptance_pairs.append({"selection": case_rows,
                                             "resources": prepared.pipeline_resources})
            added += prepared.observation["hypothetical_add_cap"]
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            return None
    result = evaluate_selection_cases(paired)
    if result is None:
        return None
    output = {"schema": "sraf_arc_relax_replay_v1",
            "scope": "operator_frozen_first_primary_legacy_parser_strict_vs_bounded_additions",
            "hypothetical_added": added, "comparison": result,
            "pilot_scope": "exhausted_nonzero_strict_linked_event_legacy_parser_only",
            "pilot_status_counts": pilot_status_counts,
            "pilot_comparison": evaluate_selection_cases(pilot_paired) if pilot_paired else None,
            "pipeline_scope": "exhausted_primary_returned_count_as_result_limit_no_live_refill",
            "pipeline_status_counts": pipeline_status_counts,
            "pipeline_comparison": evaluate_selection_cases(pipeline_paired) if pipeline_paired else None}
    if _acceptance_policy is None:
        return output
    acceptance = None
    if len(acceptance_pairs) == len(cases):
        acceptance = screen_selection_acceptance({"policy": _acceptance_policy,
                                                   "cases": acceptance_pairs})
        if acceptance is None:
            return None
    failures = sum(count for reason, count in pipeline_status_counts.items()
                   if reason not in ("pipeline_parity", "not_pilot_eligible"))
    status = ("BLOCKED" if failures else "INCOMPLETE" if acceptance is None
              else acceptance["status"])
    return {"schema": "sraf_arc_relax_pipeline_acceptance_v1",
            "scope": "offline_frozen_builder_and_refill_only_no_live_io",
            "status": status, "production_authorized": False,
            "attempted_cases": len(measured_cases),
            "unattempted_cases": len(cases) - len(measured_cases),
            "pipeline_failure_cases": failures,
            "replay": output,
            "measured_resources": evaluate_resource_cases(measured_cases) if measured_cases else None,
            "acceptance": acceptance}


def screen_relax_pipeline_acceptance(fixture):
    """One local run binds human labels, actual builder parity and timing.

    Force the operator to explicitly turn off ARC observations for both
    arms. Only the private candidate parameter changes selection. Never
    treat this zero-provider-IO boundary as full report resource usage.
    """
    if (type(fixture) is not dict or set(fixture) != {"policy", "cases"}
            or not _valid_policy(fixture["policy"])):
        return None
    if os.getenv("SRAF_ARC_MODE") != "off":
        return {"schema": "sraf_arc_relax_pipeline_acceptance_v1",
                "scope": "offline_frozen_builder_and_refill_only_no_live_io",
                "status": "INCOMPLETE", "production_authorized": False,
                "reason": "explicit_arc_off_required"}
    return replay_relax_cases(fixture["cases"], _acceptance_policy=fixture["policy"])
