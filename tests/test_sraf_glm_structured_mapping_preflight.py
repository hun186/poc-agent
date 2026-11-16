"""No-network privacy-safe GLM TEXT Mapping preflight regressions."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tools.sraf_glm_structured_mapping_preflight import inspect

ROOT = Path(__file__).resolve().parents[1]


def _mapping():
    return {
        "properties": {
            "multidim_event_json": {
                "type": "nested",
                "properties": {
                    "Event_Summary": {"type": "text"},
                    "Event": {
                        "type": "nested", "properties": {
                            "consequence": {"type": "text"},
                            "relation": {"type": "text"},
                            "action": {"type": "keyword"},
                        },
                    },
                    "Person": {
                        "type": "nested", "properties": {
                            "action": {"type": "text"},
                            "relation": {"type": "text"},
                            "stance": {"type": "keyword"},
                        },
                    },
                    "Impact": {
                        "type": "nested", "properties": {
                            "impact_description": {"type": "text"},
                        },
                    },
                    "core_entities": {"type": "keyword"},
                    "facet": {"type": "keyword"},
                    "locations": {"type": "keyword"},
                },
            },
        },
    }


def _run(*paths):
    return subprocess.run(
        [sys.executable, "-m",
         "tools.sraf_glm_structured_mapping_preflight",
         *(str(p) for p in paths)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )


def _save(path: Path, mapping):
    path.write_text(json.dumps({
        "private-news-index": {"mappings": mapping,
                               "secret": "PRIVATE-INDEX-METADATA"},
    }))
    path.chmod(0o600)


def test_correct_nested_and_text_contract_without_chinese_analyzer_claim():
    result = inspect(_mapping())
    assert result["result"] == "PASS_COMPATIBLE"
    assert result["structured_text_on_ab_ready"] is True
    assert result["nested_verified"] == result["nested_expected"] == 4
    assert result["text_verified"] == result["text_expected"] == 6
    assert result["chinese_analyzer_quality"] == "NOT_VERIFIED"
    assert result["date_event_id_evidence"] == "NOT_TESTED"
    assert result["live_es_identity"] == "NOT_ATTESTED_BY_TOOL"


@pytest.mark.parametrize("change,category", [
    (lambda m: m["properties"]["multidim_event_json"].update({"type": "object"}),
     "nested_type_mismatch_count"),
    (lambda m: m["properties"]["multidim_event_json"]["properties"]["Event"].update(
        {"type": "object"}), "nested_type_mismatch_count"),
    (lambda m: m["properties"]["multidim_event_json"]["properties"]["Impact"]["properties"][
        "impact_description"].update({"type": "keyword"}),
     "text_type_mismatch_count"),
    (lambda m: m["properties"]["multidim_event_json"]["properties"]["Person"]["properties"][
        "action"].update({"type": "keyword"}),
     "text_type_mismatch_count"),
    (lambda m: m["properties"]["multidim_event_json"]["properties"].pop("Event_Summary"),
     "text_missing_count"),
    (lambda m: m["properties"]["multidim_event_json"]["properties"].pop("Impact"),
     "nested_missing_count"),
])
def test_missing_wrong_type_or_non_nested_path_must_block_on_ab(change, category):
    mapping = _mapping()
    change(mapping)
    result = inspect(mapping)
    assert result["result"] == "NOT_READY"
    assert result["structured_text_on_ab_ready"] is False
    assert result[category] >= 1
    assert result["search_recall_quality"] == "NOT_TESTED"


def test_keyword_fields_are_not_required_as_text():
    mapping = _mapping()
    md = mapping["properties"]["multidim_event_json"]["properties"]
    # "Event.action", "Person.stance", "core_entities", "facet" and
    # "locations" are keyword in the GLM blueprint and are not planned TEXT.
    assert md["Event"]["properties"]["action"]["type"] == "keyword"
    assert md["Person"]["properties"]["stance"]["type"] == "keyword"
    assert inspect(mapping)["structured_text_on_ab_ready"]


@pytest.mark.parametrize("broken", [
    {}, {"properties": []}, {"properties": None},
])
def test_missing_mapping_properties_fails_without_inventing_compatibility(broken):
    with pytest.raises(ValueError):
        inspect(broken)


def test_cli_emits_no_private_mapping_identity(tmp_path):
    p = tmp_path / "secret-mapping.json"
    _save(p, _mapping())
    run = _run(p)
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("SRAF_GLM_MAPPING={")
    metrics = json.loads(run.stdout.strip().split("=", 1)[1])
    assert metrics["result"] == "PASS_COMPATIBLE"
    assert "PRIVATE-INDEX" not in run.stdout + run.stderr
    assert "private-news-index" not in run.stdout + run.stderr
    assert str(p) not in run.stdout + run.stderr


def test_cli_partial_mapping_reports_not_ready_not_pass(tmp_path):
    p = tmp_path / "partial.json"
    bad = _mapping()
    bad["properties"]["multidim_event_json"]["properties"]["Event"]["properties"][
        "consequence"]["type"] = "keyword"
    _save(p, bad)
    run = _run(p)
    assert run.returncode == 2
    assert run.stdout.startswith("SRAF_GLM_MAPPING={")
    metrics = json.loads(run.stdout.strip().split("=", 1)[1])
    assert metrics["text_type_mismatch_count"] == 1
    assert metrics["structured_text_on_ab_ready"] is False


def test_reject_world_readable_symlink_fifo_ambiguous_and_duplicate_json(tmp_path):
    p = tmp_path / "private.json"
    _save(p, _mapping())
    p.chmod(0o644)
    assert _run(p).returncode == 2
    p.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(p)
    assert _run(link).returncode == 2
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    assert _run(fifo).returncode == 2
    ambiguous = tmp_path / "two-indices.json"
    ambiguous.write_text(json.dumps({
        "index1": {"mappings": _mapping()},
        "index2": {"mappings": _mapping()},
    }))
    ambiguous.chmod(0o600)
    assert _run(ambiguous).returncode == 2
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"index1":{"mappings":{"properties":{}},'
                         '"mappings":{"properties":{}}}}')
    duplicate.chmod(0o600)
    assert _run(duplicate).returncode == 2
