"""OFF-1B configured-selector discovery regression tests (no live ES)."""
from __future__ import annotations

import copy
import json

import pytest

from agent.es.mock_es_client import REQUIREMENT_E2E_MAPPING
from tools import sraf_airgap_off1b_es_index_discovery as discovery


def _root(tmp_path, yaml_text="topic_index_map: {}\n"):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "indexes.yaml").write_text(yaml_text, encoding="utf-8")
    cert = tmp_path / "agent" / "certs" / "http_ca.crt"
    cert.parent.mkdir(parents=True, exist_ok=True)
    cert.write_text("unit test CA placeholder", encoding="utf-8")
    return tmp_path


def _cfg(**kwargs):
    return {
        "ES_URL": "https://192.168.0.99:9200",
        "ES_USERNAME": "user-secret",
        "ES_PASSWORD": "password-secret",
        "APP_ENV": "prod",
        **kwargs,
    }


def _base_mapping(index):
    return json.dumps({index: {"mappings": {"properties": {
        "rawInfo": {"properties": {"content": {"type": "text"}}},
        "communication": {"properties": {"subject": {"type": "text"}}},
    }}}}).encode()


def _fake_get(monkeypatch, mapping_overrides=None, missing=(), multi=(),
              san_warning=False, search_fail=(), recorder=None):
    mappings = mapping_overrides or {}

    def fake(host, port, path, username, password, ca, *, warn_only_ip_san=False):
        assert host == "192.168.0.99" and port == 9200
        if recorder is not None:
            recorder.append(path)
        why = ("https_response_ca_only_ip_san_mismatch"
               if san_warning else "https_response_received")
        if path == "/":
            return 200, b'{"cluster_name":"c","version":{"number":"8.0"}}', why
        if path == "/_security/_authenticate":
            return 200, json.dumps({
                "username": username, "enabled": True,
                "authentication_realm": {"type": "file"},
                "lookup_realm": {"type": "file"},
                "authentication_type": "realm",
            }).encode(), why
        if path.startswith("/_resolve/index/"):
            name = path.split("/")[-1]
            if name in missing:
                return 404, b"{}", why
            if name in multi:
                return 200, json.dumps({"indices": [
                    {"name": name + "_a"}, {"name": name + "_b"}
                ]}).encode(), why
            return 200, json.dumps({"indices": [{"name": name}]}).encode(), why
        if path.endswith("/_mapping"):
            index = path.split("/")[1]
            return 200, mappings.get(index, _base_mapping(index)), why
        if "/_search?" in path:
            if path.split("/")[1] in search_fail:
                return 403, b"{}", why
            return 200, b'{"hits":{"hits":[]}}', why
        raise AssertionError("Unexpected network request " + path)

    monkeypatch.setattr(discovery.transport, "_https_get", fake)


def test_merged_configs_and_role_evidence(tmp_path):
    root = _root(tmp_path, """topic_index_map:
  news:
    indexes: [primary, optional]
  naval:
    indexes: [ships]
default_indexes: [base]
""")
    (root / "config" / "indexes.prod.yaml").write_text("""topic_index_map:
  news:
    indexes: [later, primary]
default_indexes: [secondary]
""", encoding="utf-8")
    entries, warnings = discovery.discover(root, _cfg(ES_INDEX="primary,stale"))
    roles = {row["_name"]: row["role"] for row in entries}
    assert roles == {
        "primary": "ACTIVE_REQUIRED", "stale": "UNRESOLVED",
        "optional": "ACTIVE_OPTIONAL", "later": "ACTIVE_OPTIONAL",
        "ships": "ACTIVE_OPTIONAL",
    }
    assert warnings == []
    entries, _ = discovery.discover(root, _cfg())
    assert entries[0]["_name"] == "secondary"
    assert entries[0]["role"] == "UNRESOLVED"


def test_legacy_only_env_not_mislabeled_abandoned(tmp_path):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [current]
""")
    entries, warnings = discovery.discover(root, _cfg(ES_INDEX="oldindex"))
    roles = {entry["_name"]: entry["role"] for entry in entries}
    assert roles == {"oldindex": "UNRESOLVED", "current": "ACTIVE_OPTIONAL"}
    assert warnings == []


def test_no_hardcoded_news_index_and_no_fixture_when_unconfigured(tmp_path):
    root = _root(tmp_path)
    entries, errors = discovery.discover(root, _cfg())
    assert entries == []
    assert errors == ["no_verified_selectors"]


def test_explicit_fixture_conflict_isolated(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [prodindex]
""")
    _fake_get(monkeypatch)
    result = discovery.observe(
        _cfg(ES_INDEX="prodindex", REQUIREMENT_E2E_ES_INDEX="prodindex"),
        root=root)
    assert len(result["results"]) == 1
    row = result["results"][0]
    assert row["role"] == "UNRESOLVED"
    assert row["index_probe"] == "FAIL"
    assert row["reason"] == "acceptance_index_conflict"


def test_no_network_never_contacts_es_and_redacts_all_sources(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  sensitive:
    indexes: [internal_secret_idx]
""")
    monkeypatch.setattr(discovery.transport, "_https_get",
                        lambda *args, **kwargs: pytest.fail("network not allowed"))
    result = discovery.observe(_cfg(ES_INDEX="other_private"),
                               root=root, no_network=True)
    serialized = json.dumps(result)
    for term in ("internal_secret_idx", "other_private", "user-secret",
                 "password-secret", "192.168.0.99", "sensitive"):
        assert term not in serialized
    assert result["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert all(x["index_probe"] == "NOT_TESTED" for x in result["results"])


def test_missing_required_does_not_block_remaining_topic(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [required, independent]
""")
    calls = []
    _fake_get(monkeypatch, missing=("required",), recorder=calls)
    result = discovery.observe(_cfg(ES_INDEX="required"), root=root,
                               strict_ip_san=True)
    first, second = result["results"]
    assert first["role"] == "MISSING_REQUIRED"
    assert first["index_probe"] == "FAIL"
    assert first["reason"] == "required_index_missing"
    assert second["index_probe"] == "PASS"
    assert second["mapping_probe"] == "PASS"
    assert "/independent/_mapping" in calls


def test_optional_missing_and_alias_multi_do_not_block_independent(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [missing_optional, multiple_alias, available]
""")
    _fake_get(monkeypatch, missing=("missing_optional",),
              multi=("multiple_alias",))
    r = discovery.observe(_cfg(), root=root, strict_ip_san=True)["results"]
    assert [x["index_probe"] for x in r] == ["WARN", "WARN", "PASS"]
    assert r[-1]["mapping_probe"] == "PASS"


def test_distinct_rag_multidim_and_e2e_profiles(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [plain, partial]
""")
    partial = {"partial": {"mappings": {"properties": {
        "rawInfo": {"properties": {"content": {"type": "text"}}},
        "multidim_event_json": {"type": "nested", "properties": {}},
    }}}}
    _fake_get(monkeypatch, mapping_overrides={
        "partial": json.dumps(partial).encode(),
        "requirement_e2e_fixture": json.dumps({
            "requirement_e2e_fixture": REQUIREMENT_E2E_MAPPING
        }).encode(),
    })
    rows = discovery.observe(
        _cfg(REQUIREMENT_E2E_ES_INDEX="requirement_e2e_fixture"),
        root=root, strict_ip_san=True)["results"]
    assert [(r["role"], r["mapping_probe"], r["reason"]) for r in rows] == [
        ("ACTIVE_OPTIONAL", "PASS", "rag_mapping_baseline"),
        ("ACTIVE_OPTIONAL", "WARN", "rag_ok_multidim_mapping_partial"),
        ("E2E_FIXTURE", "PASS", "e2e_mapping_compatible"),
    ]


def test_warning_san_never_claims_mapping_or_search_verified(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [news1]
""")
    calls = []
    _fake_get(monkeypatch, san_warning=True, recorder=calls)
    result = discovery.observe(_cfg(), root=root)
    assert result["identity_warning"] is True
    assert result["tls_validation"] == "WARN"
    assert result["auth"] == "NOT_VERIFIED"
    assert result["results"][0]["mapping_probe"] == "WARN"
    assert not any("_search?" in path for path in calls)
    assert result["feature_acceptance"] == "NOT_TESTED"


def test_strict_search_is_opt_in_size_zero_and_no_document_reads(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  live:
    indexes: [ok, denied]
""")
    calls = []
    _fake_get(monkeypatch, search_fail=("denied",), recorder=calls)
    rows = discovery.observe(_cfg(), root=root, strict_ip_san=True,
                             read_only_search=True)["results"]
    assert [x["search_probe"] for x in rows] == ["PASS", "NOT_VERIFIED"]
    assert all("size=0&track_total_hits=false" in x
               for x in calls if "_search?" in x)
    assert all(x["feature_acceptance"] == "NOT_TESTED" for x in rows)


def test_external_selected_yaml_is_not_read(tmp_path):
    root = _root(tmp_path)
    outside = tmp_path.parent / "operator-private-index-config.yaml"
    outside.write_text("topic_index_map: {secrets: {indexes: [secret]}}")
    entries, warnings = discovery.discover(root, _cfg(INDEXES_CONFIG=str(outside)))
    assert entries == []
    assert "index_config_outside_trusted_root" in warnings


def test_invalid_and_wildcard_selectors_never_probed(tmp_path, monkeypatch):
    root = _root(tmp_path, """topic_index_map:
  x:
    indexes: ["*","good", "bad/_search", "_all"]
""")
    calls = []
    _fake_get(monkeypatch, recorder=calls)
    rows = discovery.observe(_cfg(), root=root, strict_ip_san=True)["results"]
    # The runtime loader may accept wildcard selectors; diagnostic refuses them.
    assert [x["role"] for x in rows] == ["ACTIVE_OPTIONAL"]
    assert len(rows) == 1
    assert all("*" not in call and "_all" not in call for call in calls)


@pytest.mark.parametrize("payload,reason", [
    (b"[]", "es_selector_response_invalid"),
    (b'{"indices":[{"name":"a"},{"name":"b"}]}',
     "es_selector_multiple_targets"),
    (b'{"indices":[{"name":"*"}]}', "es_selector_response_invalid"),
])
def test_index_resolution_is_safe(payload, reason):
    _, received, _ = discovery._resolve_payload(payload, "candidate")
    assert received == reason
