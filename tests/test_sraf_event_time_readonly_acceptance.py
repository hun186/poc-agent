"""Offline safety and contract tests for the actual news_test read-only probe.

The remote transport is mocked. Tests never read dotenv, open sockets,
access Elasticsearch, or persist article text/credentials.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tools import sraf_event_time_readonly_acceptance as probe


def _mapping(valid=True):
    def child(*, date=False):
        props = {"time_iso": {"type": "date"}} if date else {
            "event_ids": {"type": "keyword"}
        }
        return {"type": "nested", "properties": props}
    return {
        "news_test": {"mappings": {"properties": {
            "multidim_event_json": {
                "type": "nested", "properties": {
                    "Event": child(date=True),
                    "Event_Timeline": child(date=True) if valid
                    else {"type": "object", "properties": {}},
                    "evidence_snippets": child(),
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
                    missing_timeline=False, paging_dup=False):
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

    def fake_get(host, port, path, username, password, ca):
        assert host == "192.168.0.18" and port == 9200
        assert username == "readonly_user"
        assert password == "SENSITIVE_PASS_DO_NOT_PRINT"
        assert str(ca) == "/tmp/fake-ca.pem"
        requests.append(path)
        if tls_failure:
            return None, None, "es_tls_identity_unverified"
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
        return 200, json.dumps(body, ensure_ascii=False).encode(), "https_response_received"

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
