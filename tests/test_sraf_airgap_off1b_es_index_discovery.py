"""Configured ES discovery: deterministic unit evidence only, NOT live acceptance."""
from __future__ import annotations

import json

import pytest

from tools import sraf_airgap_off1b_es_index_discovery as discovery


def _write_config(root, text, name="indexes.yaml"):
    folder = root / "config"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def _cfg(**overrides):
    return {
        "APP_ENV": "production",
        "ES_URL": "https://192.168.10.5:9200",
        "ES_USERNAME": "operator",
        "ES_PASSWORD": "TOP_SECRET",
        **overrides,
    }


def _mapping(index, *, text=True, multidim=None):
    properties = {}
    if text:
        properties["rawInfo"] = {
            "properties": {"content": {"type": "text"}},
        }
    if multidim is not None:
        properties["multidim_event_json"] = multidim
    return json.dumps({
        index: {"mappings": {"properties": properties}},
    }).encode()


def _network(monkeypatch, results=None, *, base_warning=False):
    """Fake only transport; real config discovery and mapping predicates run."""
    calls = []
    monkeypatch.setattr(discovery.es, "_observe", lambda *a, **k: {
        "configuration": "RESOLVED",
        "https_probe": "PASS",
        "auth": "NOT_VERIFIED",
        "tls_validation": "WARN" if base_warning else "PASS",
        "identity_warning": base_warning,
        "reason": "es_mapping_delegated_to_discovery",
        "feature_acceptance": "NOT_TESTED",
    })
    monkeypatch.setattr(discovery.es, "_trusted_ca_file", lambda *a: object())
    monkeypatch.setattr(discovery.es, "_parse_endpoint", lambda *a: (
        {"port": 9200}, "192.168.10.5"
    ))

    def https_get(host, port, path, user, password, ca, **kwargs):
        calls.append(path)
        assert user == "operator" and password == "TOP_SECRET"
        assert host == "192.168.10.5" and port == 9200
        assert path.endswith("/_mapping")
        index = path.split("/")[1]
        return (results or {}).get(index, (
            200, _mapping(index), "https_response_received"
        ))
    monkeypatch.setattr(discovery.es, "_https_get", https_get)
    return calls


def test_index_loader_topic_merge_and_environment_priority(tmp_path):
    _write_config(tmp_path, """topic_index_map:
  sea: {indexes: [ship_a]}
  news: {indexes: [news_a]}
default_indexes: [default_yaml]
""")
    _write_config(tmp_path, """topic_index_map:
  sea: {indexes: [ship_b, ship_a]}
default_indexes: [new_default]
""", "indexes.production.yaml")
    targets, notes = discovery.discover(
        _cfg(ES_INDEX="runtime_main,second_default"), tmp_path)
    assert [x["_selector"] for x in targets] == [
        "runtime_main", "second_default", "ship_a", "ship_b", "news_a"
    ]
    assert targets[0]["classification"] == "ACTIVE_REQUIRED"
    assert targets[1]["classification"] == "ACTIVE_OPTIONAL"
    assert targets[2]["sources"] == ["topic_index_map"]
    assert notes == []


def test_production_without_development_index_is_supported(tmp_path):
    _write_config(tmp_path, """topic_index_map:
  military: {indexes: [production_ships]}
default_indexes: [production_docs]
""")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert [i["_selector"] for i in targets] == [
        "production_docs", "production_ships"
    ]
    assert notes == []


def test_legacy_singular_default_is_not_pretended_to_be_active(tmp_path):
    _write_config(tmp_path, "default_index: retired_legacy\n")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert targets == []
    assert "legacy_default_index_key_ignored" in notes
    assert "runtime_default_fallback_not_attested" in notes


def test_old_named_index_in_active_env_is_not_falsely_declared_legacy(tmp_path):
    _write_config(tmp_path, "topic_index_map: {}\n")
    targets, _ = discovery.discover(_cfg(ES_INDEX="satmeta"), tmp_path)
    assert targets[0]["classification"] == "ACTIVE_REQUIRED"


def test_explicit_e2e_fixture_is_separate_and_conflict_is_not_accepted(tmp_path):
    _write_config(tmp_path, "default_indexes: [main_docs]\n")
    targets, notes = discovery.discover(_cfg(
        REQUIREMENT_E2E_ES_INDEX="fixture_index"), tmp_path)
    assert targets[-1]["classification"] == "E2E_FIXTURE"
    assert notes == []
    targets2, notes2 = discovery.discover(_cfg(
        REQUIREMENT_E2E_ES_INDEX="main_docs"), tmp_path)
    assert len(targets2) == 1
    assert "e2e_production_selector_conflict" in notes2


def test_unbounded_or_unsafe_selector_is_never_sent_or_reported(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: ['*', '../private', 'good_docs']\n")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert [x["_selector"] for x in targets] == ["good_docs"]
    assert "index_selector_unsafe_or_invalid" in notes
    report = discovery.diagnose(_cfg(), tmp_path, no_network=True)
    assert "private" not in json.dumps(report)
    assert "good_docs" not in json.dumps(report)


def test_config_only_never_contacts_elasticsearch(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [index_a]\n")
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("network attempted"))
    report = discovery.diagnose(_cfg(), tmp_path, no_network=True)
    assert report["results"][0]["mapping_probe"] == "NOT_TESTED"
    assert report["feature_acceptance"] == "NOT_TESTED"


def test_multiple_real_selectors_keep_independent_results(tmp_path, monkeypatch):
    _write_config(tmp_path, """default_indexes: [required]
topic_index_map:
  other: {indexes: [optional_bad, optional_good]}
""")
    calls = _network(monkeypatch, {
        "optional_bad": (200, _mapping("optional_bad", text=False),
                         "https_response_received"),
    })
    report = discovery.diagnose(_cfg(), tmp_path)
    assert [i["mapping_probe"] for i in report["results"]] == [
        "PASS", "WARN", "PASS"
    ]
    assert calls == ["/required/_mapping", "/optional_bad/_mapping",
                     "/optional_good/_mapping"]
    assert report["results"][1]["reason"] == "rag_reference_mapping_missing"
    assert "TOP_SECRET" not in json.dumps(report)
    for hidden in ("required", "optional_bad", "optional_good"):
        assert hidden not in json.dumps(report)


def test_missing_required_fails_but_independent_optional_continues(tmp_path, monkeypatch):
    _write_config(tmp_path, """default_indexes: [required]
topic_index_map:
  second: {indexes: [optional]}
""")
    calls = _network(monkeypatch, {
        "required": (404, b"{}", "https_response_received")
    })
    report = discovery.diagnose(_cfg(), tmp_path)
    assert [x["mapping_probe"] for x in report["results"]] == ["FAIL", "PASS"]
    assert calls == ["/required/_mapping", "/optional/_mapping"]
    assert report["results"][0]["reason"] == "required_index_missing"


def test_missing_optional_is_warning_not_global_failure(tmp_path, monkeypatch):
    _write_config(tmp_path, """default_indexes: [good]
topic_index_map:
  extra: {indexes: [absent]}
""")
    _network(monkeypatch, {"absent": (404, b"", "https_response_received")})
    report = discovery.diagnose(_cfg(), tmp_path)
    assert report["results"][1]["mapping_probe"] == "WARN"
    assert report["results"][1]["reason"] == "optional_index_missing"


def test_alias_resolution_uses_only_selected_mapping_and_rejects_many_targets(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [alias_1, alias_many]\n")
    _network(monkeypatch, {
        "alias_1": (200, _mapping("real_concrete"),
                    "https_response_received"),
        "alias_many": (200, json.dumps({
            "idx_a": {"mappings": {}},
            "idx_b": {"mappings": {}},
        }).encode(), "https_response_received"),
    })
    report = discovery.diagnose(_cfg(), tmp_path)
    assert report["results"][0]["selector_resolution"] == "ALIAS_OR_DATA_STREAM"
    assert report["results"][1]["selector_resolution"] == "MULTIPLE"
    assert report["results"][1]["mapping_probe"] == "SKIP"


def test_multidim_profile_separate_from_rag_reference(tmp_path):
    compatible = {
        "type": "nested",
        "properties": {"Event": {"type": "nested",
                                 "properties": {"event_id": {"type": "keyword"}}}},
    }
    broken = {"type": "object", "properties": {}}
    assert discovery.inspect_mapping(_mapping("a", multidim=compatible),
                                     "a", "ACTIVE_REQUIRED", "rawInfo.content") == (
        "PASS", "rag_reference_mapping_compatible", "DIRECT", "PASS")
    status, reason, _, md = discovery.inspect_mapping(
        _mapping("a", multidim=broken), "a", "ACTIVE_REQUIRED", "rawInfo.content")
    assert status == "PASS" and md == "WARN"
    assert reason == "rag_reference_mapping_compatible"


def test_e2e_fixture_uses_existing_requirement_subset_predicate():
    from agent.es.mock_es_client import REQUIREMENT_E2E_MAPPING
    payload = json.dumps({"fixture": REQUIREMENT_E2E_MAPPING}).encode()
    status, reason, _, _ = discovery.inspect_mapping(
        payload, "fixture", "E2E_FIXTURE", "rawInfo.content")
    assert status == "PASS"
    assert reason == "e2e_mapping_subset_compatible"


def test_tls_ca_only_warning_cannot_look_like_verified_pass(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    _network(monkeypatch, base_warning=True)
    report = discovery.diagnose(_cfg(), tmp_path)
    assert report["base_probe"]["tls_validation"] == "WARN"
    assert report["results"][0]["mapping_probe"] == "WARN"
    assert report["results"][0]["feature_acceptance"] == "NOT_TESTED"


def test_late_tls_identity_failure_stops_es_only_and_clears_aggregated_status(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [one, two]\n")
    calls = _network(monkeypatch, {
        "one": (None, None, "es_tls_identity_unverified")
    })
    report = discovery.diagnose(_cfg(), tmp_path, strict_ip_san=True)
    assert calls == ["/one/_mapping"]
    assert report["base_probe"]["tls_validation"] == "FAIL"
    assert report["results"][1]["reason"] == "es_tls_preflight_blocked"


def test_positive_mapping_is_not_a_live_rag_claim(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    _network(monkeypatch)
    report = discovery.diagnose(_cfg(), tmp_path, show_index_names=True)
    assert report["results"][0]["selector"] == "docs"
    assert report["results"][0]["mapping_probe"] == "PASS"
    assert report["results"][0]["query_probe"] == "NOT_TESTED"
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert report["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


def test_base_auth_failure_blocks_mapping_for_all_selected_targets(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [one, two]\n")
    monkeypatch.setattr(discovery.es, "_observe", lambda *a, **k: {
        "configuration": "RESOLVED", "https_probe": "PASS",
        "auth": "NOT_VERIFIED", "tls_validation": "PASS",
        "identity_warning": False, "reason": "es_auth_access_denied",
        "feature_acceptance": "NOT_TESTED",
    })
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("unverified auth network"))
    report = discovery.diagnose(_cfg(), tmp_path)
    assert [v["mapping_probe"] for v in report["results"]] == [
        "NOT_TESTED", "NOT_TESTED"
    ]
    assert all(v["reason"] == "es_base_preflight_not_satisfied"
               for v in report["results"])


def test_no_implicit_index_name_in_report_even_when_bad_mapping(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [operator_only_name]\n")
    _network(monkeypatch, {
        "operator_only_name": (200, b'{"operator_only_name":{"mappings":{"properties":[]}}}',
                               "https_response_received")
    })
    report = discovery.diagnose(_cfg(), tmp_path)
    assert report["results"][0]["reason"] == "es_mapping_response_invalid"
    assert "operator_only_name" not in json.dumps(report)


def test_nonobject_topic_override_replaces_old_indexes_in_selected_runtime(
        tmp_path, monkeypatch):
    _write_config(tmp_path, """default_indexes: [real_default]
topic_index_map:
  sea: {indexes: [stale_index]}
""")
    _write_config(tmp_path, """topic_index_map:
  sea: disabled
""", "indexes.production.yaml")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert [target["_selector"] for target in targets] == ["real_default"]
    assert "topic_config_invalid" in notes
    calls = _network(monkeypatch)
    discovery.diagnose(_cfg(), tmp_path)
    assert calls == ["/real_default/_mapping"]


def test_replacing_scalar_topic_with_new_mapping_restores_only_new_indexes(tmp_path):
    _write_config(tmp_path, "topic_index_map: {sea: disabled}\n")
    _write_config(tmp_path, """topic_index_map:
  sea: {indexes: [restored]}
""", "indexes.production.yaml")
    targets, _ = discovery.discover(_cfg(), tmp_path)
    assert [t["_selector"] for t in targets] == ["restored"]


def test_alias_backing_index_cannot_point_at_e2e_fixture(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [prod_alias]\n")
    calls = _network(monkeypatch, {
        "prod_alias": (200, _mapping("secret_fixture"),
                       "https_response_received"),
    })
    report = discovery.diagnose(
        _cfg(REQUIREMENT_E2E_ES_INDEX="secret_fixture"), tmp_path)
    assert calls[0] == "/prod_alias/_mapping"
    assert report["results"][0]["mapping_probe"] == "FAIL"
    assert report["results"][0]["selector_resolution"] == "FIXTURE_CONFLICT"
    assert report["results"][0]["reason"] == "e2e_production_selector_conflict"
    assert "secret_fixture" not in json.dumps(report)
    assert "prod_alias" not in json.dumps(report)


def test_runtime_valid_hyphenated_reference_field_matches_mapping(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    payload = json.dumps({
        "docs": {"mappings": {"properties": {
            "content-text": {"type": "text"}
        }}}
    }).encode()
    _network(monkeypatch, {
        "docs": (200, payload, "https_response_received")
    })
    report = discovery.diagnose(
        _cfg(SRA_REFERENCE_TEXT_FIELD="content-text"), tmp_path)
    assert report["results"][0]["mapping_probe"] == "PASS"


def test_invalid_reference_field_uses_runtime_default_not_skip(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    _network(monkeypatch)
    report = discovery.diagnose(
        _cfg(SRA_REFERENCE_TEXT_FIELD="../index"), tmp_path)
    assert report["results"][0]["mapping_probe"] == "PASS"



def test_numeric_yaml_index_scalars_match_runtime_normalization(tmp_path, monkeypatch):
    _write_config(tmp_path, """default_indexes: [123, '123', 0]
topic_index_map:
  group: {indexes: [456, '456', 789, null]}
""")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert [t["_selector"] for t in targets] == ["123", "0", "456", "789"]
    assert targets[0]["classification"] == "ACTIVE_REQUIRED"
    assert notes == []
    calls = _network(monkeypatch)
    report = discovery.diagnose(_cfg(), tmp_path)
    assert calls == [
        "/123/_mapping", "/0/_mapping", "/456/_mapping", "/789/_mapping",
    ]
    assert len(report["results"]) == 4


def test_late_san_warning_survives_fixture_alias_conflict(tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [production_alias]\n")
    calls = _network(monkeypatch, {
        "production_alias": (
            200, _mapping("fixture_name"),
            "https_response_ca_only_ip_san_mismatch",
        ),
    })
    report = discovery.diagnose(
        _cfg(REQUIREMENT_E2E_ES_INDEX="fixture_name"), tmp_path)
    assert calls == ["/production_alias/_mapping"]
    assert report["base_probe"]["identity_warning"] is True
    assert report["base_probe"]["tls_validation"] == "WARN"
    assert report["results"][0]["mapping_probe"] == "WARN"
    assert report["results"][0]["selector_resolution"] == "FIXTURE_CONFLICT"
    assert report["results"][0]["reason"] == "es_mapping_identity_unverified"
    assert "fixture_name" not in json.dumps(report)
    assert "production_alias" not in json.dumps(report)


@pytest.mark.parametrize("target_result", [
    (404, b"{}", "https_response_received"),
    (200, _mapping("docs", text=False), "https_response_received"),
    (200, _mapping("fixture_name"), "https_response_received"),
])
def test_base_identity_warning_downgrades_negative_mapping_evidence(
        tmp_path, monkeypatch, target_result):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    _network(monkeypatch, {"docs": target_result}, base_warning=True)
    report = discovery.diagnose(
        _cfg(REQUIREMENT_E2E_ES_INDEX="fixture_name"), tmp_path)
    assert report["base_probe"]["identity_warning"] is True
    assert report["base_probe"]["tls_validation"] == "WARN"
    assert report["results"][0]["mapping_probe"] == "WARN"
    assert report["results"][0]["reason"] == "es_mapping_identity_unverified"
    assert report["results"][0]["feature_acceptance"] == "NOT_TESTED"


def test_late_san_warning_downgrades_required_not_found_and_continues(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [required, other]\n")
    calls = _network(monkeypatch, {
        "required": (404, b"{}", "https_response_ca_only_ip_san_mismatch"),
    })
    report = discovery.diagnose(_cfg(), tmp_path)
    assert calls == ["/required/_mapping", "/other/_mapping"]
    assert report["base_probe"]["tls_validation"] == "WARN"
    assert report["results"][0]["mapping_probe"] == "WARN"
    assert report["results"][1]["mapping_probe"] == "WARN"


def test_cli_san_warning_and_unverified_missing_index_is_partial_only(
        tmp_path, monkeypatch, capsys):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: _cfg())
    _network(monkeypatch, {
        "docs": (404, b"{}", "https_response_ca_only_ip_san_mismatch"),
    })
    assert discovery.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["base_probe"]["tls_validation"] == "WARN"
    assert result["results"][0]["mapping_probe"] == "WARN"


def test_cli_propagates_base_auth_failure_exit_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: _cfg())
    monkeypatch.setattr(discovery, "diagnose", lambda *a, **k: {
        "base_probe": {
            "configuration": "RESOLVED", "https_probe": "PASS",
            "auth": "FAIL", "tls_validation": "PASS",
        }, "results": [], "mode": "PARTIAL_ONLY_NOT_ACCEPTANCE",
    })
    assert discovery.main([]) == 1
    assert json.loads(capsys.readouterr().out)["base_probe"]["auth"] == "FAIL"


def test_cli_propagates_invalid_endpoint_configuration_exit_one(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: _cfg())
    monkeypatch.setattr(discovery, "diagnose", lambda *a, **k: {
        "base_probe": {
            "configuration": "INVALID", "https_probe": "SKIP",
            "auth": "NOT_TESTED", "tls_validation": "NOT_TESTED",
        }, "results": [], "mode": "PARTIAL_ONLY_NOT_ACCEPTANCE",
    })
    assert discovery.main([]) == 1
