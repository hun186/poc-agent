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


@pytest.mark.parametrize("override_key", [
    "INDEXES_CONFIG", "INDEX_CONFIG", "INDEXES_CONFIGS",
])
def test_explicit_external_index_file_matches_runtime_selected_targets(
        tmp_path, monkeypatch, override_key):
    repo = tmp_path / "checkout"
    repo.mkdir()
    private = tmp_path / "deployment" / "production.yaml"
    private.parent.mkdir()
    private.write_text("""default_indexes: [external_default]
topic_index_map:
  sea: {indexes: [external_topic]}
""", encoding="utf-8")
    cfg = _cfg(**{override_key: str(private)})
    targets, notes = discovery.discover(cfg, repo)
    assert [x["_selector"] for x in targets] == [
        "external_default", "external_topic",
    ]
    assert "external_index_config_not_release_attested" in notes
    calls = _network(monkeypatch)
    report = discovery.diagnose(cfg, repo)
    assert calls == [
        "/external_default/_mapping", "/external_topic/_mapping",
    ]
    assert [i["mapping_probe"] for i in report["results"]] == [
        "PASS", "PASS",
    ]
    visible = json.dumps(report)
    assert str(private) not in visible
    assert "external_default" not in visible
    assert "external_topic" not in visible
    assert "TOP_SECRET" not in visible
    assert report["feature_acceptance"] == "NOT_TESTED"


def test_external_selected_config_preserves_multi_file_order_and_bounds(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    first = tmp_path / "managed" / "one.yaml"
    second = tmp_path / "managed" / "two.yaml"
    first.parent.mkdir()
    first.write_text("""default_indexes: [first_default]
topic_index_map:
  sea: {indexes: [old_topic]}
""", encoding="utf-8")
    second.write_text("""default_indexes: [new_default]
topic_index_map:
  sea: {indexes: [new_topic]}
""", encoding="utf-8")
    cfg = _cfg(INDEXES_CONFIGS=f"{first},{second}")
    targets, notes = discovery.discover(cfg, repo)
    assert [x["_selector"] for x in targets] == [
        "new_default", "old_topic", "new_topic",
    ]
    assert "external_index_config_not_release_attested" in notes



@pytest.mark.parametrize("invalid_content", [
    "- malformed\n",
    "disabled\n",
    "bad: [unclosed\n",
])
def test_invalid_later_selected_yaml_aborts_all_selector_probes(
        tmp_path, monkeypatch, invalid_content, capsys):
    _write_config(tmp_path, """default_indexes: [stale_index]
topic_index_map:
  other: {indexes: [old_topic]}
""")
    _write_config(tmp_path, invalid_content, "indexes.production.yaml")
    cfg = _cfg(ES_INDEX="explicit_active",
               REQUIREMENT_E2E_ES_INDEX="requirement_e2e_fixture_target")
    targets, notes = discovery.discover(cfg, tmp_path)
    assert targets == []
    assert any(n in notes for n in (
        "index_config_invalid_root", "index_config_yaml_invalid",
    ))
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("stale ES request attempted"))
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("stale Mapping GET attempted"))
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert report["base_probe"]["https_probe"] == "SKIP"
    visible = json.dumps(report)
    for secret in ("stale_index", "old_topic", "explicit_active",
                   "requirement_e2e_fixture_target", "TOP_SECRET"):
        assert secret not in visible
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: cfg)
    assert discovery.main([]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["selector_discovery"] == "INVALID_CONFIG"


@pytest.mark.parametrize("empty_content", ["", "null\n", "[]\n", "0\n"])
def test_empty_yaml_root_follows_runtime_empty_mapping_fallback(
        tmp_path, empty_content):
    _write_config(tmp_path, "default_indexes: [retained]\n")
    _write_config(tmp_path, empty_content, "indexes.production.yaml")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert [v["_selector"] for v in targets] == ["retained"]
    assert "index_config_invalid_root" not in notes
    assert "index_config_yaml_invalid" not in notes


def test_invalid_external_yaml_root_blocks_prior_file_and_network(
        tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    good = managed / "base.yaml"
    broken = managed / "override.yaml"
    good.write_text("default_indexes: [stale_external]\n", encoding="utf-8")
    broken.write_text("- malformed\n", encoding="utf-8")
    cfg = _cfg(INDEXES_CONFIGS=f"{good},{broken}",
               ES_INDEX="explicit_active")
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("network attempted"))
    report = discovery.diagnose(cfg, repo)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert "external_index_config_not_release_attested" in report["notes"]
    assert "index_config_invalid_root" in report["notes"]
    assert str(good) not in json.dumps(report)
    assert str(broken) not in json.dumps(report)



@pytest.mark.parametrize("invalid", [
    "default_indexes: 123\n",
    "default_indexes: true\n",
    "topic_index_map:\n  sea: {indexes: 123}\n",
    "topic_index_map:\n  sea: {indexes: true}\n",
])
def test_invalid_truthy_index_value_aborts_all_probes(
        tmp_path, monkeypatch, capsys, invalid):
    _write_config(tmp_path, "default_indexes: [stale_yaml]\n")
    _write_config(tmp_path, invalid, "indexes.production.yaml")
    cfg = _cfg(ES_INDEX="env_index", REQUIREMENT_E2E_ES_INDEX="requirement_e2e_fixture")
    selected, notes = discovery.discover(cfg, tmp_path)
    assert selected == []
    assert "index_config_indexes_invalid" in notes
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("ES connection attempted"))
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("Mapping request attempted"))
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert report["base_probe"]["https_probe"] == "SKIP"
    visible = json.dumps(report)
    for secret in ("stale_yaml", "env_index", "requirement_e2e_fixture", "TOP_SECRET"):
        assert secret not in visible
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: cfg)
    assert discovery.main([]) == 1
    assert json.loads(capsys.readouterr().out)[
        "selector_discovery"] == "INVALID_CONFIG"


def test_valid_mapping_index_keys_are_normalized_like_runtime(tmp_path):
    _write_config(tmp_path, "default_indexes: {primary: ignored}\n")
    selected, notes = discovery.discover(_cfg(), tmp_path)
    assert [v["_selector"] for v in selected] == ["primary"]
    assert "index_config_indexes_invalid" not in notes


def test_selected_utf8_decode_failure_aborts_prior_config_and_es(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [stale_index]\n")
    (tmp_path / "config" / "indexes.production.yaml").write_bytes(
        b"default_indexes: [ok]\n\xff")
    cfg = _cfg(ES_INDEX="explicit_env")
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("ES connection attempted"))
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("Mapping attempted"))
    selected, notes = discovery.discover(cfg, tmp_path)
    assert selected == []
    assert "index_config_unavailable" in notes
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert "stale_index" not in json.dumps(report)


def test_selected_existing_config_open_failure_aborts_es(
        tmp_path, monkeypatch):
    from pathlib import Path

    _write_config(tmp_path, "default_indexes: [stale]\n")
    _write_config(tmp_path, "default_indexes: [unused]\n",
                  "indexes.production.yaml")
    original_open = Path.open

    def reject_one(path, *args, **kwargs):
        if path.name == "indexes.production.yaml":
            raise PermissionError("sensitive/operator/config/path")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_one)
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("ES connection attempted"))
    cfg = _cfg(ES_INDEX="explicit_env")
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert "index_config_unavailable" in report["notes"]
    assert "sensitive" not in json.dumps(report)


def test_missing_selected_config_remains_nonfatal_like_runtime(tmp_path):
    _write_config(tmp_path, "default_indexes: [present]\n")
    targets, notes = discovery.discover(_cfg(), tmp_path)
    assert [x["_selector"] for x in targets] == ["present"]
    assert "index_config_unavailable" not in notes


def test_oversized_selected_config_blocks_even_explicit_env_index(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [stale]\n")
    (tmp_path / "config" / "indexes.production.yaml").write_bytes(
        b"x" * (discovery.MAX_CONFIG_BYTES + 1))
    cfg = _cfg(ES_INDEX="explicit_env")
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("ES connection attempted"))
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert "index_config_not_read" in report["notes"]


def test_external_selected_config_oversize_is_not_read(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    private = tmp_path / "managed" / "oversized.yaml"
    private.parent.mkdir()
    private.write_bytes(b"x" * (discovery.MAX_CONFIG_BYTES + 1))
    targets, notes = discovery.discover(
        _cfg(INDEXES_CONFIG=str(private)), repo)
    assert targets == []
    assert "index_config_not_read" in notes
    assert "external_index_config_not_release_attested" in notes
    assert "runtime_default_fallback_not_attested" not in notes


def test_implicit_repo_config_symlink_cannot_read_external_file(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    private = tmp_path / "outside.yaml"
    private.write_text("default_indexes: [outside_index]\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "indexes.yaml").symlink_to(private)
    targets, notes = discovery.discover(_cfg(), repo)
    assert targets == []
    assert "index_config_outside_checkout_not_selected" in notes
    assert "outside_index" not in json.dumps(notes)


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
        REQUIREMENT_E2E_ES_INDEX="requirement_e2e_fixture_index"), tmp_path)
    assert targets[-1]["classification"] == "E2E_FIXTURE"
    assert notes == []
    _write_config(tmp_path, "default_indexes: [requirement_e2e_main_docs]\n")
    targets2, notes2 = discovery.discover(_cfg(
        REQUIREMENT_E2E_ES_INDEX="requirement_e2e_main_docs"), tmp_path)
    assert targets2 == []
    assert "e2e_production_selector_conflict" in notes2



@pytest.mark.parametrize("yaml_text,extra", [
    ("default_indexes: [requirement_e2e_production_fixture]\n", {}),
    ("topic_index_map:\n  sea: {indexes: [requirement_e2e_production_fixture]}\n",
     {"ES_INDEX": "production_main"}),
    ("default_indexes: [production_main, requirement_e2e_production_fixture]\n", {}),
])
def test_literal_fixture_conflict_is_invalid_without_network(
        tmp_path, monkeypatch, capsys, yaml_text, extra):
    _write_config(tmp_path, yaml_text)
    cfg = _cfg(REQUIREMENT_E2E_ES_INDEX="requirement_e2e_production_fixture", **extra)
    selected, notes = discovery.discover(cfg, tmp_path)
    assert selected == []
    assert "e2e_production_selector_conflict" in notes
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("ES connection attempted"))
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("Mapping GET attempted"))
    report = discovery.diagnose(cfg, tmp_path, show_index_names=True)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert report["base_probe"]["https_probe"] == "SKIP"
    assert report["feature_acceptance"] == "NOT_TESTED"
    output = json.dumps(report)
    assert "requirement_e2e_production_fixture" not in output
    assert "production_main" not in output
    assert "TOP_SECRET" not in output
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: cfg)
    assert discovery.main([]) == 1
    assert json.loads(capsys.readouterr().out)[
        "selector_discovery"] == "INVALID_CONFIG"


def test_nonstring_topic_keys_produce_runtime_selected_indices(
        tmp_path, monkeypatch):
    _write_config(tmp_path, """topic_index_map:
  123: {indexes: [topic_numeric]}
  true: {indexes: [topic_boolean]}
default_indexes: [main_docs]
""")
    selected, notes = discovery.discover(_cfg(), tmp_path)
    assert [v["_selector"] for v in selected] == [
        "main_docs", "topic_numeric", "topic_boolean",
    ]
    assert "topic_config_invalid" not in notes
    calls = _network(monkeypatch)
    report = discovery.diagnose(_cfg(), tmp_path)
    assert calls == [
        "/main_docs/_mapping", "/topic_numeric/_mapping",
        "/topic_boolean/_mapping",
    ]
    assert [v["mapping_probe"] for v in report["results"]] == [
        "PASS", "PASS", "PASS",
    ]
    exposed = json.dumps(report)
    for hidden in ("main_docs", "topic_numeric", "topic_boolean",
                   "TOP_SECRET"):
        assert hidden not in exposed


def test_numeric_topic_key_merges_across_selected_configs(tmp_path):
    _write_config(tmp_path, """topic_index_map:
  123: {indexes: [first_numeric]}
default_indexes: [docs]
""")
    _write_config(tmp_path, """topic_index_map:
  123: {indexes: [second_numeric]}
""", "indexes.production.yaml")
    selected, notes = discovery.discover(_cfg(), tmp_path)
    assert [v["_selector"] for v in selected] == [
        "docs", "first_numeric", "second_numeric",
    ]
    assert notes == []



@pytest.mark.parametrize("selector_source", ["default", "topic", "environment"])
def test_runtime_default_e2e_requirement_e2e_fixture_name_conflict_fails_without_network(
        tmp_path, monkeypatch, capsys, selector_source):
    fixture = discovery.REQUIREMENT_E2E_INDEX
    if selector_source == "default":
        config = "default_indexes: [" + fixture + "]\n"
        cfg = _cfg()
    elif selector_source == "topic":
        config = "topic_index_map:\n  job: {indexes: [" + fixture + "]}\n"
        cfg = _cfg(ES_INDEX="normal_docs")
    else:
        config = "default_indexes: [normal_docs]\n"
        cfg = _cfg(ES_INDEX=fixture)
    _write_config(tmp_path, config)
    selected, notes = discovery.discover(cfg, tmp_path)
    assert selected == []
    assert "e2e_production_selector_conflict" in notes
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("network attempted"))
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("Mapping attempted"))
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert report["base_probe"]["https_probe"] == "SKIP"
    assert fixture not in json.dumps(report)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: cfg)
    assert discovery.main([]) == 1
    assert json.loads(capsys.readouterr().out)[
        "selector_discovery"] == "INVALID_CONFIG"


def test_runtime_default_fixture_alias_is_conflict_not_compatible(
        tmp_path, monkeypatch):
    fixture = discovery.REQUIREMENT_E2E_INDEX
    _write_config(tmp_path, "default_indexes: [production_alias]\n")
    calls = _network(monkeypatch, {
        "production_alias": (
            200, _mapping(fixture), "https_response_received"),
    })
    report = discovery.diagnose(_cfg(), tmp_path)
    assert calls == ["/production_alias/_mapping"]
    assert len(report["results"]) == 1
    assert report["results"][0]["mapping_probe"] == "FAIL"
    assert report["results"][0]["selector_resolution"] == "FIXTURE_CONFLICT"
    assert report["results"][0]["reason"] == "e2e_production_selector_conflict"
    assert fixture not in json.dumps(report)


def test_unconfigured_default_fixture_is_protected_but_not_probed(
        tmp_path, monkeypatch):
    _write_config(tmp_path, "default_indexes: [normal_docs]\n")
    calls = _network(monkeypatch)
    report = discovery.diagnose(_cfg(REQUIREMENT_E2E_ES_INDEX=""), tmp_path)
    assert calls == ["/normal_docs/_mapping"]
    assert len(report["results"]) == 1
    assert report["results"][0]["mapping_probe"] == "PASS"


@pytest.mark.parametrize("failure", ["forced-recursion", "deep-yaml"])
def test_recursive_selected_yaml_is_invalid_config_without_network(
        tmp_path, monkeypatch, capsys, failure):
    _write_config(tmp_path, "default_indexes: [stale_index]\n")
    depth = 1400
    _write_config(
        tmp_path,
        "default_indexes: " + "[" * depth + "docs" + "]" * depth + "\n",
        "indexes.production.yaml")
    if failure == "forced-recursion":
        actual_load = discovery.yaml.safe_load
        def parser(stream):
            if "indexes.production.yaml" in str(getattr(stream, "name", "")):
                raise RecursionError("internal recursion details")
            return actual_load(stream)
        monkeypatch.setattr(discovery.yaml, "safe_load", parser)
    cfg = _cfg(ES_INDEX="explicit_docs")
    monkeypatch.setattr(discovery.es, "_observe",
                        lambda *a, **k: pytest.fail("network attempted"))
    monkeypatch.setattr(discovery.es, "_https_get",
                        lambda *a, **k: pytest.fail("Mapping attempted"))
    selected, notes = discovery.discover(cfg, tmp_path)
    assert selected == []
    assert "index_config_yaml_invalid" in notes
    report = discovery.diagnose(cfg, tmp_path)
    assert report["selector_discovery"] == "INVALID_CONFIG"
    assert report["results"] == []
    assert report["base_probe"]["https_probe"] == "SKIP"
    assert "stale_index" not in json.dumps(report)
    assert "explicit_docs" not in json.dumps(report)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_effective_runtime_config",
                        lambda _: cfg)
    assert discovery.main([]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["selector_discovery"] == "INVALID_CONFIG"
    assert "internal recursion details" not in json.dumps(output)


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
        "prod_alias": (200, _mapping("requirement_e2e_secret_fixture"),
                       "https_response_received"),
    })
    report = discovery.diagnose(
        _cfg(REQUIREMENT_E2E_ES_INDEX="requirement_e2e_secret_fixture"), tmp_path)
    assert calls[0] == "/prod_alias/_mapping"
    assert report["results"][0]["mapping_probe"] == "FAIL"
    assert report["results"][0]["selector_resolution"] == "FIXTURE_CONFLICT"
    assert report["results"][0]["reason"] == "e2e_production_selector_conflict"
    assert "requirement_e2e_secret_fixture" not in json.dumps(report)
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
            200, _mapping("requirement_e2e_fixture_name"),
            "https_response_ca_only_ip_san_mismatch",
        ),
    })
    report = discovery.diagnose(
        _cfg(REQUIREMENT_E2E_ES_INDEX="requirement_e2e_fixture_name"), tmp_path)
    assert calls[0] == "/production_alias/_mapping"
    assert report["base_probe"]["identity_warning"] is True
    assert report["base_probe"]["tls_validation"] == "WARN"
    assert report["results"][0]["mapping_probe"] == "WARN"
    assert report["results"][0]["selector_resolution"] == "FIXTURE_CONFLICT"
    assert report["results"][0]["reason"] == "es_mapping_identity_unverified"
    assert "requirement_e2e_fixture_name" not in json.dumps(report)
    assert "production_alias" not in json.dumps(report)


@pytest.mark.parametrize("target_result", [
    (404, b"{}", "https_response_received"),
    (200, _mapping("docs", text=False), "https_response_received"),
    (200, _mapping("requirement_e2e_fixture_name"), "https_response_received"),
])
def test_base_identity_warning_downgrades_negative_mapping_evidence(
        tmp_path, monkeypatch, target_result):
    _write_config(tmp_path, "default_indexes: [docs]\n")
    _network(monkeypatch, {"docs": target_result}, base_warning=True)
    report = discovery.diagnose(
        _cfg(REQUIREMENT_E2E_ES_INDEX="requirement_e2e_fixture_name"), tmp_path)
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
