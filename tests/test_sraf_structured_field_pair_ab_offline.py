"""No-network A/B on separate private ES snapshots; candidate != valid Evidence."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.sraf_structured_field_pair_ab_offline import compare_pair
from test_sraf_topic_shadow import _hit, GROUPS

ROOT = Path(__file__).resolve().parents[1]


def _case(role, hits):
    return {
        "snapshot_role": role,
        "original_question": "主題：加薩\n請整理2023年停火與醫療",
        "date_from": "2023-08-24", "date_to": "2023-08-24",
        "term_groups": [sorted(x) for x in GROUPS],
        "effective_terms": ["加薩", "停火", "人道援助"],
        "query_for_snippet": "加薩 停火 PRIVATE-QUERY",
        "es_hits": hits,
    }


def _source(docid, text, *, index="news_test", event="E1", day="2023-08-24"):
    hit = _hit()
    hit["_id"] = docid
    hit["_index"] = index
    hit["_source"]["multidim_event_json"][0]["Event"] = [{
        "event_id": event, "time_iso": day, "time_precision": "day",
    }]
    hit["_source"]["multidim_event_json"][0]["evidence_snippets"] = [{
        "text": text, "event_ids": [event],
    }]
    return hit


def test_increased_candidates_does_not_claim_increased_valid_evidence(monkeypatch):
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")  # Must be neutralized.
    original = _source("SENSITIVE-A", "加薩 停火 人道援助 PRIVATE-SECRET")
    off = _case("baseline", [original])
    # A second document returned because of GLM TEXT should boosting, but
    # its passage has no matching date/topic; never count as relevant Evidence.
    extra = _source("SENSITIVE-B", "蘇丹 會議 PRIVATE-SECRET",
                    day="2022-08-24")
    on = _case("structured_on", [copy.deepcopy(original), extra])
    metrics = compare_pair(off, on)
    assert metrics["baseline_candidates"] == 1
    assert metrics["enhanced_candidates"] == 2
    assert metrics["candidate_new_sources"] == 1
    assert metrics["baseline_date_topic_valid_evidence"] == 1
    assert metrics["enhanced_date_topic_valid_evidence"] == 1
    assert metrics["new_candidate_sources_without_valid_evidence"] == 1
    assert metrics["new_candidate_sources_with_valid_evidence"] == 0
    assert metrics["valid_sources_gained"] == 0
    assert metrics["strong_sources_gained"] == 0
    assert metrics["human_precision_assessment"] == "REQUIRED"
    assert metrics["live_es_query"] == "NOT_RUN_BY_TOOL"
    assert os.environ["SRAF_TOPIC_MATCH_ADAPTIVE"] == "on"
    assert "SENSITIVE" not in json.dumps(metrics)


def test_valid_new_source_requires_canonical_matching_date_and_topic():
    a = _source("PRIVATE-A", "加薩 停火 人道援助")
    good = _source("PRIVATE-B", "加薩 醫療 停火 人道援助")
    bad = _source("PRIVATE-C", "加薩 醫療 停火 人道援助",
                  day="2023-08-25")
    metrics = compare_pair(
        _case("baseline", [a]),
        _case("structured_on", [a, good, bad]),
    )
    assert metrics["candidate_new_sources"] == 2
    assert metrics["new_candidate_sources_with_valid_evidence"] == 1
    assert metrics["new_candidate_sources_without_valid_evidence"] == 1
    assert metrics["valid_sources_gained"] == 1
    assert metrics["strong_sources_gained"] == 1
    assert metrics["enhanced_date_topic_valid_evidence"] == 2
    assert metrics["baseline_date_topic_valid_evidence"] == 1


def test_reranked_away_baseline_valid_source_is_reported_as_loss():
    a = _source("PRIVATE-A", "加薩 停火 人道援助")
    b = _source("PRIVATE-B", "加薩 醫療 停火 人道援助")
    metrics = compare_pair(
        _case("baseline", [a]), _case("structured_on", [b]),
    )
    assert metrics["candidate_new_sources"] == 1
    assert metrics["candidate_lost_sources"] == 1
    assert metrics["valid_sources_gained"] == 1
    assert metrics["valid_sources_lost"] == 1
    assert metrics["baseline_valid_sources"] == 1
    assert metrics["enhanced_valid_sources"] == 1


def test_es_doc_identity_uses_index_and_id_not_uuid_or_event_ids():
    a = _source("SAME-ES-ID", "加薩 停火 人道援助",
                index="index_a")
    b = _source("SAME-ES-ID", "加薩 停火 人道援助",
                index="index_b")
    # The duplicated application UUID/Event E1 must not merge ES sources.
    metrics = compare_pair(
        _case("baseline", [a]), _case("structured_on", [a, b]),
    )
    assert metrics["candidate_new_sources"] == 1
    assert metrics["valid_sources_gained"] == 1


@pytest.mark.parametrize("mutate", [
    lambda x: x.update({"original_question": "PRIVATE-MISMATCH"}),
    lambda x: x.update({"date_to": "2023-08-25"}),
    lambda x: x.update({"term_groups": [["OTHER"]]}),
    lambda x: x.update({"effective_terms": ["SOMETHING"]}),
    lambda x: x.update({"query_for_snippet": "PRIVATE-DIFFERENT"}),
    lambda x: x.update({"snapshot_role": "baseline"}),
    lambda x: x["es_hits"].append(copy.deepcopy(x["es_hits"][0])),
    lambda x: x["es_hits"][0].pop("_id"),
])
def test_mismatched_case_identity_duplicates_or_roles_fail_closed(mutate):
    a = _case("baseline", [_source("SENSITIVE-ID", "加薩 停火 人道援助")])
    b = _case("structured_on", [copy.deepcopy(a["es_hits"][0])])
    mutate(b)
    with pytest.raises((ValueError, KeyError)):
        compare_pair(a, b)


def _private(path: Path, case: dict) -> None:
    path.write_text(json.dumps(case, ensure_ascii=False))
    path.chmod(0o600)


def _run(*paths):
    return subprocess.run(
        [sys.executable, "-m", "tools.sraf_structured_field_pair_ab_offline",
         *(str(p) for p in paths)],
        cwd=ROOT, capture_output=True, text=True, timeout=25,
    )


def test_private_cli_reports_count_only_and_no_path_source_question(tmp_path):
    a, b = tmp_path / "private-baseline.json", tmp_path / "private-on.json"
    row = _source("VERY-SECRET-ES-ID", "加薩 停火 人道援助 PRIVATE-SECRET")
    _private(a, _case("baseline", [row]))
    _private(b, _case("structured_on", [row]))
    result = _run(a, b)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("SRAF_STRUCTURED_AB={")
    metrics = json.loads(result.stdout.strip().split("=", 1)[1])
    assert metrics["baseline_valid_sources"] == 1
    assert metrics["enhanced_valid_sources"] == 1
    assert metrics["query_elapsed_and_token_cost"] == "NOT_MEASURED"
    output = result.stdout + result.stderr
    for secret in ("VERY-SECRET", "PRIVATE", "加薩",
                   "2023-08-24", str(a), str(b)):
        assert secret not in output


def test_untrusted_private_snapshot_paths_refused(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    row = _source("secret-id", "加薩 停火 人道援助")
    _private(a, _case("baseline", [row]))
    _private(b, _case("structured_on", [row]))
    b.chmod(0o644)
    failure = _run(a, b)
    assert failure.returncode == 2
    assert "INCOMPLETE" in failure.stdout
    assert str(b) not in failure.stdout + failure.stderr
    b.chmod(0o600)
    link = tmp_path / "source-link"
    link.symlink_to(b)
    failure = _run(a, link)
    assert failure.returncode == 2
    assert "INCOMPLETE" in failure.stdout


def test_fifo_input_does_not_block_and_is_rejected(tmp_path):
    a = tmp_path / "fifo"
    os.mkfifo(a, 0o600)
    row = _source("SENSITIVE-ID", "加薩 停火 人道援助")
    b = tmp_path / "on.json"
    _private(b, _case("structured_on", [row]))
    result = _run(a, b)
    assert result.returncode == 2
    assert "INCOMPLETE" in result.stdout



def test_zero_baseline_and_zero_enhanced_are_valid_ab_comparisons():
    a = _source("PRIVATE-GOOD", "加薩 停火 人道援助")
    b = compare_pair(
        _case("baseline", []),
        _case("structured_on", [a]),
    )
    assert b["baseline_candidates"] == 0
    assert b["baseline_strict_evidence"] == 0
    assert b["valid_sources_gained"] == 1
    assert b["new_candidate_sources_with_valid_evidence"] == 1
    lost = compare_pair(
        _case("baseline", [a]), _case("structured_on", []),
    )
    assert lost["candidate_lost_sources"] == 1
    assert lost["valid_sources_lost"] == 1
    assert lost["enhanced_date_topic_valid_evidence"] == 0
    both = compare_pair(
        _case("baseline", []), _case("structured_on", []),
    )
    assert both["baseline_candidates"] == both["enhanced_candidates"] == 0


def test_fallback_effective_term_is_weak_not_strict_evidence():
    # No two axes are matched, but single "加薩" matches effective_terms,
    # causing legacy fallback_any_term (policy defaults to strict).
    only_one = _source("PRIVATE-FALLBACK", "加薩")
    a = compare_pair(
        _case("baseline", [only_one]),
        _case("structured_on", [only_one]),
    )
    assert a["baseline_date_topic_valid_evidence"] == 1
    assert a["baseline_strict_evidence"] == 0
    assert a["enhanced_strict_evidence"] == 0
    assert a["baseline_weak_evidence"] == 1
    assert a["baseline_strong_evidence"] == 0


def test_private_cli_supports_zero_hit_baseline_without_weakening_old_cli(tmp_path):
    from tools.sraf_topic_adaptive_ab_offline import _private_read
    baseline = tmp_path / "empty.json"
    enhanced = tmp_path / "with_valid.json"
    _private(baseline, _case("baseline", []))
    _private(enhanced, _case("structured_on", [
        _source("SENSITIVE-NEW", "加薩 停火 人道援助"),
    ]))
    # Old Topic Match same-snapshot A/B still rejects an empty input.
    with pytest.raises(ValueError):
        _private_read(str(baseline))
    assert _private_read(str(baseline), allow_empty_hits=True)["es_hits"] == []
    result = _run(baseline, enhanced)
    assert result.returncode == 0, result.stderr
    metrics = json.loads(result.stdout.strip().split("=", 1)[1])
    assert metrics["baseline_candidates"] == 0
    assert metrics["valid_sources_gained"] == 1
    assert "SENSITIVE" not in result.stdout + result.stderr
