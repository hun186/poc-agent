"""Offline safety and contract tests for the actual news_test read-only probe.

The remote transport is mocked. Tests never read dotenv, open sockets,
access Elasticsearch, or persist article text/credentials.
"""
from __future__ import annotations

import json
from pathlib import Path
import copy
import pytest
from urllib.parse import parse_qs, urlsplit

from tools import sraf_event_time_readonly_acceptance as probe


def _mapping(valid=True):
    def child(*, kind):
        if kind == "Event":
            props = {
                "event_id": {"type": "keyword"},
                "time_iso": {"type": "date"},
                "time_precision": {"type": "keyword"},
            }
        elif kind == "Event_Timeline":
            props = {
                "event_ids": {"type": "keyword"},
                "time_iso": {"type": "date"},
                "time_precision": {"type": "keyword"},
            }
        else:
            props = {
                "event_ids": {"type": "keyword"},
                "text": {"type": "text"},
            }
        return {"type": "nested", "properties": props}
    return {
        "news_test": {"mappings": {"properties": {
            "multidim_event_json": {
                "type": "nested", "properties": {
                    "Event": child(kind="Event"),
                    "Event_Timeline": child(kind="Event_Timeline") if valid
                    else {"type": "object", "properties": {}},
                    "evidence_snippets": child(kind="evidence_snippets"),
                },
            },
        }}}
    }

def _doc(doc_id, day="2025-06-17"):
    return {"_index": "news_test", "_id": doc_id, "_source": {
        "uuid": "private-document-id",
        "multidim_event_json": [{
            "article_date_iso": "2026-08-01",
            "Event": [{
                "event_id": "E1", "time_iso": day,
                "time_precision": "day",
            }],
            "Event_Timeline": [{
                "event_ids": ["E1"], "time_iso": day,
                "time_precision": "day",
            }],
            "evidence_snippets": [{
                "text": "SENSITIVE PRIVATE ARTICLE CONTENT",
                "event_ids": ["E1"],
            }],
        }],
    }}


def _response(documents, *, count=2):
    return {"_shards": {"total": 1, "successful": 1, "failed": 0},
            "timed_out": False,
            "hits": {"total": {"value": count, "relation": "eq"},
                     "hits": documents}}


def _fake_transport(monkeypatch, *, valid_mapping=True, tls_failure=False,
                    san_mismatch=False, missing_timeline=False, paging_dup=False,
                    failure_path=None, failure_kind=None):
    from tools import sraf_airgap_off1b_auto as conf
    from tools import sraf_airgap_off1b_es_https_mapping as es
    monkeypatch.setattr(conf, "_effective_runtime_config", lambda root: {
        "ES_URL": "https://192.168.0.18:9200",
        "ES_USERNAME": "readonly_user",
        "ES_PASSWORD": "SENSITIVE_PASS_DO_NOT_PRINT",
    })
    monkeypatch.setattr(
        es, "_trusted_ca_file", lambda root: Path("/tmp/fake-ca.pem")
    )
    requests = []

    def fake_get(host, port, path, username, password, ca, *, warn_only_ip_san=False):
        assert host == "192.168.0.18" and port == 9200
        assert username == "readonly_user"
        assert password == "SENSITIVE_PASS_DO_NOT_PRINT"
        assert str(ca) == "/tmp/fake-ca.pem"
        requests.append(path)
        if tls_failure:
            return None, None, "es_tls_identity_unverified"
        if san_mismatch and not warn_only_ip_san:
            return None, None, "es_tls_identity_unverified"
        if failure_path == path:
            reason = ("https_response_ca_only_ip_san_mismatch"
                      if san_mismatch else "https_response_received")
            if failure_kind == "401":
                return 401, b"not authorized", reason
            if failure_kind == "invalid_json":
                return 200, b"SENSITIVE_BAD_JSON_NOT_TO_PRINT", reason
            if failure_kind == "transport":
                return None, None, "es_https_transport_unavailable_ip_san_mismatch"
            if failure_kind == "ca_failure":
                return None, None, "es_tls_identity_unverified"
            raise AssertionError("invalid fake failure_kind")
        if path == "/":
            body = {"cluster_name": "SENSITIVE_CLUSTER",
                    "version": {"number": "8.13.1"}}
        elif path == "/_security/_authenticate":
            body = {"username": "readonly_user",
                    "authentication_type": "realm",
                    "enabled": True,
                    "authentication_realm": {"type": "file", "name": "file"}}
        elif path == "/news_test/_mapping":
            body = _mapping(valid_mapping)
        elif path.startswith("/news_test/_search?"):
            params = parse_qs(urlsplit(path).query)
            request_body = json.loads(params["source"][0])
            assert params["source_content_type"] == ["application/json"]
            assert request_body["size"] <= 1
            assert request_body.get("from", 0) <= 1
            query = request_body.get("query") or {}
            if "ids" in query.get("bool", {}).get("filter", [{}])[0]:
                body = _response([_doc("a")], count=1)
            elif "Event_Timeline.time_iso" in json.dumps(query):
                body = _response([] if missing_timeline else [_doc("a")], count=1)
            else:
                body = _response(
                    [_doc("a")] if request_body.get("from", 0) == 0 or paging_dup
                    else [_doc("b")], count=2,
                )
        else:
            raise AssertionError("unexpected endpoint")
        reason = ("https_response_ca_only_ip_san_mismatch"
                  if san_mismatch else "https_response_received")
        return 200, json.dumps(body, ensure_ascii=False).encode(), reason

    monkeypatch.setattr(es, "_https_get", fake_get)
    return requests


def test_no_network_is_the_default_and_never_loads_local_configuration(monkeypatch, capsys):
    monkeypatch.setattr(
        probe, "_strict_live_observe",
        lambda *_: (_ for _ in ()).throw(AssertionError("should not probe")),
    )
    assert probe.main([]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "NOT_TESTED"
    assert data["reason"] == "network_not_enabled"
    assert data["index"] == "news_test"


def test_mapping_requires_real_nested_structure_and_index_is_fixed():
    _, problems = probe._properties(_mapping())
    assert not problems
    _, problems = probe._properties(_mapping(valid=False))
    assert "event_timeline_not_nested" in problems
    url = probe._search_request({
        "size": 1, "query": {"match_all": {}},
    })
    assert url.startswith("/news_test/_search?source=")
    assert "source_content_type=application%2Fjson" in url
    assert "/_update" not in url and "/_bulk" not in url


@pytest.mark.parametrize("child,field,problem", [
    ("Event", "event_id", "event_event_id_not_keyword"),
    ("Event", "time_precision", "event_time_precision_not_keyword"),
    ("Event_Timeline", "event_ids", "event_timeline_event_ids_not_keyword"),
    ("Event_Timeline", "time_precision", "event_timeline_time_precision_not_keyword"),
    ("evidence_snippets", "event_ids", "evidence_snippets_event_ids_not_keyword"),
    ("evidence_snippets", "text", "evidence_snippets_text_not_text"),
])
def test_missing_or_wrong_leaf_types_block_live_mapping_success(child, field, problem):
    original = _mapping()
    item = original["news_test"]["mappings"]["properties"]["multidim_event_json"]["properties"][child]["properties"]
    no_field = copy.deepcopy(original)
    del no_field["news_test"]["mappings"]["properties"]["multidim_event_json"]["properties"][child]["properties"][field]
    _, problems = probe._properties(no_field)
    assert problem in problems

    wrong_type = copy.deepcopy(original)
    wrong_type["news_test"]["mappings"]["properties"]["multidim_event_json"]["properties"][child]["properties"][field]["type"] = "object"
    _, problems = probe._properties(wrong_type)
    assert problem in problems


def test_alias_or_unexpected_mapping_index_cannot_be_attested_as_news_test():
    alias_mapping = {"production_news": _mapping()["news_test"]}
    _, problems = probe._properties(alias_mapping)
    assert problems == ["mapping_target_not_fixed_index"]
    with pytest.raises(probe.ObservationError, match="search_hit_unexpected_index"):
        probe._hits(_response([
            {**_doc("private"), "_index": "production_news"},
        ]))


@pytest.mark.parametrize("child", ["Event", "Event_Timeline"])
@pytest.mark.parametrize("precision", [
    "second", "minute", "hour", "day", "month", "year", "legacy",
])
def test_real_date_probe_request_fits_es_default_http_get_limit(child, precision):
    # This is the actual selected precision branch from SRAF's nested query
    # builder, not just a manually truncated example URL.
    nested_clause = probe._sampled_sraf_date_clause("2025-06-17", child, precision)
    body = {
        "size": 1, "_source": False,
        "query": {"bool": {"filter": [
            {"ids": {"values": ["abc123"]}},
            nested_clause,
        ]}},
    }
    path = probe._search_request(body)
    assert len(("GET " + path + " HTTP/1.1").encode("ascii")) < 4096
    assert "multidim_event_json" in nested_clause["nested"]["path"]
    assert "multidim_event_json." + child in str(nested_clause)


def test_strict_tls_real_sample_checks_dates_link_and_two_pages_without_leaking_content(
    monkeypatch, capsys
):
    requests = _fake_transport(monkeypatch)
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())
    result = probe._strict_live_observe(Path.cwd())
    assert result["status"] == "PASS_PARTIAL"
    assert result["identity"] == "STRICT_TLS_CA_IP_SAN_VERIFIED"
    assert result["mapping"] == "PASS"
    assert result["date_filter"] == "PASS"
    assert result["paging"] == "PASS"
    assert result["source_sample"]["evidence_linked"] == 2
    assert result["source_sample"]["evidence_without_link"] == 0
    assert requests[:3] == [
        "/", "/_security/_authenticate", "/news_test/_mapping",
    ]
    assert all(
        item in ("/", "/_security/_authenticate", "/news_test/_mapping")
        or item.startswith("/news_test/_search?source=")
        for item in requests
    )
    serialized = json.dumps(result)
    for forbidden in ("SENSITIVE_PRIVATE", "SENSITIVE PASS", "SENSITIVE_CLUSTER",
                      "SENSITIVE PRIVATE ARTICLE CONTENT", "private-document-id",
                      "SENSITIVE_PASS_DO_NOT_PRINT", "192.168.0.18"):
        assert forbidden not in serialized


def test_mapping_incompatible_stops_before_search(monkeypatch):
    requests = _fake_transport(monkeypatch, valid_mapping=False)
    result = probe._strict_live_observe(Path.cwd())
    assert result["status"] == "FAIL"
    assert "event_timeline_not_nested" in result["mapping_issues"]
    assert not any("/_search?" in path for path in requests)


def test_ca_or_ip_san_rejection_fail_closed_before_auth_and_mapping(monkeypatch):
    requests = _fake_transport(monkeypatch, tls_failure=True)
    try:
        probe._strict_live_observe(Path.cwd())
        assert False, "transport failure should be visible"
    except probe.ObservationError as exc:
        assert str(exc) == "es_tls_identity_unverified"
    assert requests == ["/"]


def test_strict_san_mismatch_still_blocks_basic_auth(monkeypatch):
    requests = _fake_transport(monkeypatch, san_mismatch=True)
    with pytest.raises(probe.ObservationError, match="es_tls_identity_unverified"):
        probe._strict_live_observe(Path.cwd())
    assert requests == ["/"]


def test_ca_verified_san_mismatch_warns_and_date_queries_continue(monkeypatch):
    requests = _fake_transport(monkeypatch, san_mismatch=True)
    report = probe._strict_live_observe(Path.cwd(), warn_only_ip_san=True)
    assert report["status"] == "PASS_PARTIAL"
    assert report["mapping"] == "PASS"
    assert report["date_filter"] == "PASS"
    assert report["paging"] == "PASS"
    assert report["identity"] == "CA_VERIFIED_IP_SAN_MISMATCH"
    assert report["tls_validation"] == "WARN"
    assert report["ip_san_policy"] == "WARN_ONLY"
    assert report["identity_warning"] is True
    assert report["release_tls_identity_verified"] is False
    assert report["tls_warning"] == "ip_san_mismatch_ca_chain_verified"
    assert requests[:3] == [
        "/", "/_security/_authenticate", "/news_test/_mapping",
    ]
    serialized = json.dumps(report)
    assert "SENSITIVE" not in serialized
    assert "192.168.0.18" not in serialized


def test_ca_failure_still_blocks_warning_mode(monkeypatch):
    requests = _fake_transport(monkeypatch, tls_failure=True)
    with pytest.raises(probe.ObservationError, match="es_tls_identity_unverified"):
        probe._strict_live_observe(Path.cwd(), warn_only_ip_san=True)
    assert requests == ["/"]


@pytest.mark.parametrize("failure_path,failure_kind,expected_reason,expected_tls", [
    ("/", "401", "es_http_rejected", "WARN"),
    ("/_security/_authenticate", "401", "es_http_rejected", "WARN"),
    ("/_security/_authenticate", "invalid_json", "es_response_not_json", "WARN"),
    ("/news_test/_mapping", "transport",
     "es_https_transport_unavailable_ip_san_mismatch", "WARN"),
    ("/news_test/_mapping", "ca_failure", "es_tls_identity_unverified", "FAIL"),
])
def test_warning_survives_broken_http_and_later_tls_failures(
    monkeypatch, capsys, failure_path, failure_kind, expected_reason, expected_tls
):
    # On the real entrypoint path, earlier CA-verified SAN mismatch must remain
    # in the redacted JSON even when the peer misbehaves after Basic was sent.
    requests = _fake_transport(
        monkeypatch, san_mismatch=True,
        failure_path=failure_path, failure_kind=failure_kind,
    )
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())
    assert probe.main(["--run", "--warn-only-ip-san"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == expected_reason
    assert result["identity_warning"] is True
    assert result["tls_validation"] == expected_tls
    assert result["identity"] == "CA_VERIFIED_IP_SAN_MISMATCH"
    assert result["release_tls_identity_verified"] is False
    assert result["tls_warning"] == "ip_san_mismatch_ca_chain_verified"
    assert requests[0] == "/"
    serialized = json.dumps(result)
    for secret in ("SENSITIVE", "192.168.0.18", "readonly_user"):
        assert secret not in serialized


def test_unexpected_probe_failure_also_preserves_prior_san_warning(monkeypatch, capsys):
    _fake_transport(monkeypatch, san_mismatch=True)
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())
    monkeypatch.setattr(
        probe, "_candidate_source_summary",
        lambda hits: (_ for _ in ()).throw(
            RuntimeError("SENSITIVE_ARTICLE_AND_PASSWORD")
        )
    )
    assert probe.main(["--run", "--warn-only-ip-san"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "unhandled_probe_error"
    assert result["identity_warning"] is True
    assert result["tls_validation"] == "WARN"
    assert result["release_tls_identity_verified"] is False
    assert "SENSITIVE_ARTICLE_AND_PASSWORD" not in json.dumps(result)


def test_san_warning_cannot_hide_incomplete_date_sample(monkeypatch):
    _fake_transport(monkeypatch, san_mismatch=True, missing_timeline=True)
    report = probe._strict_live_observe(Path.cwd(), warn_only_ip_san=True)
    assert report["tls_validation"] == "WARN"
    assert report["status"] == "INCOMPLETE"


def test_warn_only_is_not_release_tls_attestation_even_if_san_matches(monkeypatch):
    _fake_transport(monkeypatch)
    report = probe._strict_live_observe(Path.cwd(), warn_only_ip_san=True)
    assert report["status"] == "PASS_PARTIAL"
    assert report["identity"] == "CA_VERIFIED_IP_SAN_MATCH_OBSERVED"
    assert report["release_tls_identity_verified"] is False


def test_shell_launcher_explicit_warning_mode_and_strict_override():
    shell = (Path(__file__).resolve().parents[1] /
             "scripts/sraf_event_time_readonly.sh").read_text()
    assert "TLS_ARGS=(--warn-only-ip-san)" in shell
    assert "--strict-ip-san" in shell
    assert '"${TLS_ARGS[@]}"' in shell


def test_rare_sample_is_incomplete_not_false_pass(monkeypatch):
    _fake_transport(monkeypatch, missing_timeline=True)
    observed = probe._strict_live_observe(Path.cwd())
    assert observed["event_sample"] == "OBSERVED"
    assert observed["timeline_sample"] == "NOT_OBSERVED"
    assert observed["status"] == "INCOMPLETE"


def test_unstable_paging_cannot_pass(monkeypatch):
    _fake_transport(monkeypatch, paging_dup=True)
    observed = probe._strict_live_observe(Path.cwd())
    assert observed["paging"] == "INCONCLUSIVE"
    assert observed["status"] == "INCOMPLETE"


def test_warning_flag_requires_explicit_run():
    with pytest.raises(SystemExit) as exc:
        probe.main(["--warn-only-ip-san"])
    assert exc.value.code == 2


def test_cli_warn_mode_is_explicit_and_redacted(monkeypatch, capsys):
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())
    called = []
    def fake_observe(root, *, warn_only_ip_san=False):
        called.append((root, warn_only_ip_san))
        return {"status": "PASS_PARTIAL", "identity_warning": True,
                "tls_validation": "WARN"}
    monkeypatch.setattr(probe, "_strict_live_observe", fake_observe)
    assert probe.main(["--run", "--warn-only-ip-san"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["identity_warning"] is True
    assert called == [(Path.cwd(), True)]


def test_main_never_prints_sensitive_exceptions(monkeypatch, capsys):
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())
    monkeypatch.setattr(
        probe, "_strict_live_observe",
        lambda root: (_ for _ in ()).throw(RuntimeError("PASSWORD_HOST_URL_SECRET")),
    )
    assert probe.main(["--run"]) == 2
    result = capsys.readouterr().out
    assert "PASSWORD_HOST_URL_SECRET" not in result
    assert json.loads(result)["reason"] == "unhandled_probe_error"


def test_separate_worktree_can_use_existing_deployment_configuration_without_mutation(
    monkeypatch, tmp_path, capsys
):
    deployment = tmp_path / "deployed"
    deployment.mkdir()
    (deployment / "run_sra_api.sh").write_text("# no execution")
    captured = []
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())

    def fake_live(root):
        captured.append(root)
        return {"status": "PASS_PARTIAL", "identity": "STRICT_TLS_CA_IP_SAN_VERIFIED"}

    monkeypatch.setattr(probe, "_strict_live_observe", fake_live)
    assert probe.main(["--run", "--config-root", str(deployment)]) == 2
    assert captured == [deployment.resolve()]
    output = capsys.readouterr().out
    assert str(deployment) not in output
    assert json.loads(output)["status"] == "PASS_PARTIAL"


def test_invalid_config_root_never_loads_credentials_or_contacts_es(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(probe, "PROJECT_ROOT", Path.cwd())
    monkeypatch.setattr(
        probe, "_strict_live_observe",
        lambda root: (_ for _ in ()).throw(AssertionError("unexpected IO")),
    )
    assert probe.main(["--run", "--config-root", str(tmp_path)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "configured_repository_root_invalid"
    assert str(tmp_path) not in json.dumps(report)


def test_query_source_uri_size_cap_never_sends_oversized_path():
    try:
        probe._search_request({"size": 1, "query": {"match": {"x": "A" * 30000}}})
        assert False, "URI limit should reject"
    except probe.ObservationError as exc:
        assert str(exc) == "bounded_search_uri_too_long"
