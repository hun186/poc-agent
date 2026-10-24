"""OFF-1F real generation probe: unit contracts, never hosted LLM execution."""
from __future__ import annotations

import json
from email.message import Message
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1d_readiness_matrix as matrix
from tools import sraf_airgap_off1_probes as transport
from tools import sraf_airgap_off1f_llm_inference as inference


@pytest.fixture(autouse=True)
def _mock_attested_server(monkeypatch):
    # HTTP probe unit tests presume that the server's real PID and compatible
    # no-cloud configuration were already independently verified.
    monkeypatch.setattr(inference, "server_cloud_disabled",
                        lambda pid, port: pid == 4242)
    monkeypatch.setattr(inference, "supported_local_only_version",
                        lambda port: True)


MODEL = "private-model:latest"
URL = "http://127.0.0.1:11434/api/chat"


def _cfg(url=URL, model=MODEL):
    return {"MODEL_BASE_URL": url, "MODEL_ID": model,
            "ES_PASSWORD": "NEVER_PRINT_OR_SEND_ME"}


def _response(**overrides):
    result = {"model": MODEL, "done": True, "response": "READY",
              "eval_count": 2, "prompt_eval_count": 9}
    result.update(overrides)
    return json.dumps(result).encode("utf-8")


def _fake_post(monkeypatch, *, status=200, body=None):
    calls = []
    def send(port, payload):
        calls.append((port, json.loads(payload)))
        return status, body if body is not None else _response()
    monkeypatch.setattr(inference, "_http_post_local_generate", send)
    return calls


def _partial(record):
    assert record.feature_acceptance if hasattr(record, "feature_acceptance") else True
    assert record.check_id == "LLM-02"
    assert record.aspect == "single_bounded_generation_only"
    assert record.probe == "llm-inference"
    assert "model" not in json.dumps(record.evidence)
    assert "response" not in json.dumps(record.evidence)


def test_bounded_generation_body_and_positive_evidence(monkeypatch):
    calls = _fake_post(monkeypatch)
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert obs.status == "PASS"
    assert obs.reason == "llm_inference_generation_observed"
    assert obs.executed is True
    assert obs.evidence == {"generation_observed": True, "http_status": 200}
    assert len(calls) == 1
    port, payload = calls[0]
    assert port == 11434
    assert payload["model"] == MODEL
    assert payload["stream"] is False
    assert payload["options"]["num_predict"] == 8
    assert payload["options"]["num_ctx"] == 512
    assert payload["prompt"] == inference.PROMPT
    assert "api_key" not in str(payload).lower()
    _partial(obs)


@pytest.mark.parametrize("port,model", [
    (0, MODEL), (-1, MODEL), (65536, MODEL), (True, MODEL),
    (11434, ""), (11434, "x" * 257), (11434, "name here"),
    (11434, "a\nname"), (11434, "中文"), (11434, None),
])
def test_invalid_port_or_model_never_makes_post(monkeypatch, port, model):
    monkeypatch.setattr(inference, "_http_post_local_generate",
                        lambda *a: pytest.fail("no POST expected"))
    obs = inference.probe_local_ollama_inference(
        port, model, ollama_server_pid=4242)
    assert obs.status == "SKIP"
    assert obs.executed is False


@pytest.mark.parametrize("status,expected,reason", [
    (None, "SKIP", "llm_inference_transport_unverified"),
    (401, "SKIP", "llm_inference_service_unverified"),
    (403, "SKIP", "llm_inference_service_unverified"),
    (429, "SKIP", "llm_inference_service_unverified"),
    (503, "SKIP", "llm_inference_service_unverified"),
    (404, "FAIL", "llm_inference_http_error"),
    (400, "FAIL", "llm_inference_http_error"),
    (500, "FAIL", "llm_inference_http_error"),
])
def test_negative_http_never_false_positive(
        monkeypatch, status, expected, reason):
    calls = _fake_post(monkeypatch, status=status, body=b"SECRET FROM SERVICE")
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert obs.status == expected
    assert obs.reason == reason
    assert obs.executed is True
    assert "SECRET" not in json.dumps(obs.evidence)
    assert len(calls) == 1


@pytest.mark.parametrize("body,expected_reason", [
    (b"{not json", "llm_inference_response_invalid"),
    (b"null", "llm_inference_response_invalid"),
    (b"[]", "llm_inference_response_invalid"),
    (_response(error="internal secret"), "llm_inference_response_invalid"),
    (_response(model="another-private-model"), "llm_inference_model_unverified"),
    (_response(done=False), "llm_inference_generation_unverified"),
    (_response(done="true"), "llm_inference_generation_unverified"),
    (_response(response=""), "llm_inference_generation_unverified"),
    (_response(response="   "), "llm_inference_generation_unverified"),
    (_response(response="z" * 1025), "llm_inference_generation_unverified"),
    (_response(eval_count=0), "llm_inference_generation_unverified"),
    (_response(eval_count=True), "llm_inference_generation_unverified"),
    (_response(eval_count=9), "llm_inference_generation_unverified"),
    (_response(eval_count=None), "llm_inference_generation_unverified"),
])
def test_response_shape_and_identity_must_match(monkeypatch, body, expected_reason):
    _fake_post(monkeypatch, body=body)
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert obs.status in ("FAIL", "SKIP")
    assert obs.reason == expected_reason
    assert obs.evidence.get("generation_observed") is False
    assert MODEL not in json.dumps(obs.evidence)
    assert "internal secret" not in json.dumps(obs.evidence)


def test_oversized_http_response_is_failure(monkeypatch):
    _fake_post(monkeypatch, body=b"x" * (transport.MAX_HTTP_BYTES + 1))
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert obs.status == "FAIL"
    assert obs.reason == "llm_inference_response_invalid"


def _mock_inventory(monkeypatch, status="PASS"):
    calls = []
    def check(cfg, *, probe_network, probe_model_inventory, tcp_status):
        calls.append((probe_network, probe_model_inventory, tcp_status))
        return matrix._record("LLM-INVENTORY", "llm",
                              "named_model_inventory_only", status,
                              "configured_model_listed" if status == "PASS"
                              else "llm_inventory_not_requested")
    monkeypatch.setattr(matrix, "_llm_inventory", check)
    return calls


def _fake_nested(monkeypatch, obs=None):
    calls = []
    evidence = {"generation_observed": True, "http_status": 200}
    def run(port, model, *, ollama_server_pid=None):
        calls.append((port, model, ollama_server_pid))
        return obs or SimpleNamespace(
            check_id="LLM-02", probe="llm-inference",
            aspect="single_bounded_generation_only",
            status="PASS", reason="llm_inference_generation_observed",
            executed=True, evidence=evidence)
    monkeypatch.setattr(matrix, "probe_local_ollama_inference", run)
    return calls


@pytest.mark.parametrize("network,inventory,infer,inventory_status,expected", [
    (False, True, True, "PASS", "NOT_TESTED"),
    (True, False, True, "PASS", "NOT_TESTED"),
    (True, True, False, "PASS", "NOT_TESTED"),
    (True, True, True, "SKIP", "SKIP"),
    (True, True, True, "FAIL", "SKIP"),
    (True, True, True, "PASS", "PASS"),
])
def test_matrix_inference_three_flags_and_inventory_gate(
        monkeypatch, network, inventory, infer, inventory_status, expected):
    calls = _fake_nested(monkeypatch)
    obs = matrix._llm_inference(
        _cfg(), probe_network=network, probe_model_inventory=inventory,
        probe_model_inference=infer, inventory_status=inventory_status, ollama_server_pid=4242)
    assert obs["status"] == expected
    assert obs["depends_on"] == ["LLM-TCP", "LLM-INVENTORY"]
    assert len(calls) == (1 if expected == "PASS" else 0)
    assert obs["feature_acceptance"] == "NOT_TESTED"


@pytest.mark.parametrize("url", [
    "http://192.168.1.1:11434", "http://127.0.0.2:11434",
    "http://localhost:11434", "https://127.0.0.1:11434",
    "http://8.8.8.8:11434", "http://[::1]:11434",
    "http://127.0.0.1:11434/prefix/api/chat",
    "http://127.0.0.1:11434?model=private",
    "http://127.0.0.1:0", "",
])
def test_inference_rejects_unsafe_targets(monkeypatch, url):
    calls = _fake_nested(monkeypatch)
    obs = matrix._llm_inference(
        _cfg(url=url), probe_network=True, probe_model_inventory=True,
        probe_model_inference=True, inventory_status="PASS", ollama_server_pid=4242)
    assert obs["status"] == "SKIP"
    assert obs["reason"] == "llm_inference_endpoint_invalid"
    assert calls == []


@pytest.mark.parametrize("field,value", [
    ("model", "different"), ("done", False),
    ("status", "WARN"), ("reason", "an invented success"),
    ("http_status", 503), ("http_status", True),
    ("generation_observed", False), ("generation_observed", 1),
])
def test_nested_inference_cannot_forge_pass(monkeypatch, field, value):
    nested = SimpleNamespace(
        check_id="LLM-02", probe="llm-inference",
        aspect="single_bounded_generation_only",
        status="PASS", reason="llm_inference_generation_observed",
        executed=True, evidence={
            "generation_observed": True, "http_status": 200})
    if field == "model":
        nested.check_id = value
    elif field in ("done", "status"):
        nested.status = value if field == "status" else "SKIP"
    elif field == "reason":
        nested.reason = value
    else:
        nested.evidence[field] = value
    _fake_nested(monkeypatch, nested)
    obs = matrix._llm_inference(
        _cfg(), probe_network=True, probe_model_inventory=True,
        probe_model_inference=True, inventory_status="PASS", ollama_server_pid=4242)
    assert obs["status"] != "PASS"
    assert obs["feature_acceptance"] == "NOT_TESTED"


def test_matrix_report_partial_with_valid_stubbed_generation(monkeypatch):
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda key, component, aspect, fn:
                        matrix._record(key, component, aspect,
                                       "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_tcp_probe",
                        lambda service, cfg, *, probe_network:
                        matrix._record(
                            {"api":"API-TCP", "es":"ES-TCP", "llm":"LLM-TCP"}[service],
                            service, "configured_tcp_only", "PASS",
                            "configured_tcp_connected"))
    monkeypatch.setattr(matrix, "_api_health",
                        lambda *a, **k: matrix._record(
                            "API-HEALTH", "api", "healthz_http_only",
                            "SKIP", "network_disabled"))
    _mock_inventory(monkeypatch)
    calls = _fake_nested(monkeypatch)
    report = matrix.build_report(
        _cfg(), probe_network=True, probe_model_inventory=True,
        probe_model_inference=True, ollama_server_pid=4242)
    rows = {row["id"]: row for row in report["results"]}
    assert rows["LLM-INVENTORY"]["status"] == "PASS"
    assert rows["LLM-INFERENCE"]["status"] == "PASS"
    assert rows["LLM-INFERENCE"]["feature_acceptance"] == "NOT_TESTED"
    assert rows["WORD"]["status"] == "NOT_TESTED"
    assert rows["SQL-READ"]["status"] == "NOT_TESTED"
    assert report["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert report["overall"] == "INCOMPLETE"
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert report["network_mode"].endswith("OPTIONAL_GENERATION")
    assert len(calls) == 1


def test_cli_default_and_partial_switches_never_generate(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda *a: _cfg())
    _fake_nested(monkeypatch)
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda key, component, aspect, fn:
                        matrix._record(key, component, aspect,
                                       "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_tcp_probe",
                        lambda service, cfg, *, probe_network:
                        matrix._record(
                            {"api":"API-TCP", "es":"ES-TCP", "llm":"LLM-TCP"}[service],
                            service, "configured_tcp_only", "SKIP",
                            "network_disabled"))
    monkeypatch.setattr(matrix, "_api_health",
                        lambda *a, **k: matrix._record(
                            "API-HEALTH", "api", "healthz_http_only",
                            "SKIP", "network_disabled"))
    for args in ([], ["--probe-llm-inference"],
                 ["--probe-network", "--probe-llm-inference"]):
        assert matrix.main(args) == 2
        data = json.loads(capsys.readouterr().out)
        obs = {row["id"]: row for row in data["results"]}["LLM-INFERENCE"]
        assert obs["status"] == "NOT_TESTED"


def test_shared_transport_post_wire_safety_and_deadline(monkeypatch):
    events = []
    body = _response()
    class FakeResponse:
        raw_status_version = "HTTP/1.1"
        version = 11
        status = 200
        chunked = False
        length = len(body)
        headers = Message()
        headers["Content-Length"] = str(len(body))
        def read(self, max_bytes):
            assert max_bytes == transport.MAX_HTTP_BYTES + 1
            return body
    class FakeConnection:
        def __init__(self, port, *, deadline):
            events.append(("open", port, deadline))
        def request(self, method, path, body=None, headers=None):
            events.append(("request", method, path, body, headers))
        def getresponse(self):
            return FakeResponse()
        def close(self):
            events.append(("close",))
    monkeypatch.setattr(transport, "_DeadlineHTTPConnection", FakeConnection)
    status, result = transport._http_post_local_generate(
        11434, b'{"model":"valid","prompt":"x","stream":false}')
    assert status == 200 and result == body
    assert events[1][1:3] == ("POST", "/api/generate")
    assert events[1][4]["Content-Type"] == "application/json"
    assert events[-1] == ("close",)
    assert events[0][2] > 0
    assert transport._http_request(
        11434, "/different", method="POST", body=b"{}",
        deadline_seconds=20) == (None, None)
    assert transport._http_request(
        11434, "/api/generate", method="POST", body=b"{}",
        deadline_seconds=3) == (None, None)


def test_shared_transport_rejects_compressed_post_reply(monkeypatch):
    events = []
    body = _response()
    class FakeResponse:
        raw_status_version = "HTTP/1.1"
        version = 11
        status = 200
        chunked = False
        length = len(body)
        headers = Message()
        headers["Content-Length"] = str(len(body))
        headers["Content-Encoding"] = "gzip"
    class FakeConnection:
        def __init__(self, port, *, deadline):
            pass
        def request(self, method, path, body=None, headers=None):
            events.append((method,path))
        def getresponse(self):
            return FakeResponse()
        def close(self):
            pass
    monkeypatch.setattr(transport, "_DeadlineHTTPConnection", FakeConnection)
    assert transport._http_post_local_generate(11434, b"{}") == (None, None)
    assert events == [("POST", "/api/generate")]


@pytest.mark.parametrize("model", [
    "gpt-oss:120b-cloud", "my-local-looking-cloud-alias", MODEL,
])
def test_cloud_not_disabled_blocks_any_post_even_for_listed_alias(
        monkeypatch, model):
    monkeypatch.setattr(inference, "server_cloud_disabled",
                        lambda *args: False)
    monkeypatch.setattr(inference, "_http_post_local_generate",
                        lambda *args: pytest.fail("would forward remote model"))
    monkeypatch.setattr(inference, "supported_local_only_version",
                        lambda *args: pytest.fail("version must not be called"))
    obs = inference.probe_local_ollama_inference(
        11434, model, ollama_server_pid=4242)
    assert (obs.status, obs.reason, obs.executed) == (
        "SKIP", "llm_inference_cloud_disable_unverified", False)


@pytest.mark.parametrize("pid", [None, 0, -5, True, 1])
def test_no_explicit_server_pid_blocks_generation(monkeypatch, pid):
    monkeypatch.setattr(inference, "_http_post_local_generate",
                        lambda *args: pytest.fail("no POST permitted"))
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=pid)
    assert obs.status == "SKIP"
    assert obs.reason == "llm_inference_cloud_disable_unverified"
    assert not obs.executed


def test_old_or_unverified_server_version_blocks_generation(monkeypatch):
    monkeypatch.setattr(inference, "supported_local_only_version",
                        lambda port: False)
    monkeypatch.setattr(inference, "_http_post_local_generate",
                        lambda *args: pytest.fail("must fail closed"))
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert (obs.status, obs.executed) == ("SKIP", False)


def test_cloud_disable_must_still_hold_after_version_get(monkeypatch):
    observed = []
    def check(pid, port):
        observed.append((pid, port))
        return len(observed) == 1
    monkeypatch.setattr(inference, "server_cloud_disabled", check)
    monkeypatch.setattr(inference, "_http_post_local_generate",
                        lambda *args: pytest.fail("must not POST"))
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert obs.status == "SKIP"
    assert observed == [(4242, 11434), (4242, 11434)]


@pytest.mark.parametrize("fields", [
    {"remote_host": "https://remote.example"},
    {"remote_model": "gpt-oss:cloud"},
    {"remote_host": ""},
])
def test_remote_response_metadata_never_certifies_local_inference(
        monkeypatch, fields):
    _fake_post(monkeypatch, body=_response(**fields))
    obs = inference.probe_local_ollama_inference(
        11434, MODEL, ollama_server_pid=4242)
    assert (obs.status, obs.reason) == ("SKIP", "llm_inference_remote_response")
    assert "remote" not in json.dumps(obs.evidence)


def test_matrix_forwards_explicit_pid_and_refuses_missing_pid(monkeypatch):
    calls = _fake_nested(monkeypatch)
    kwargs = dict(probe_network=True, probe_model_inventory=True,
                  probe_model_inference=True, inventory_status="PASS")
    skipped = matrix._llm_inference(_cfg(), **kwargs)
    assert skipped["status"] == "SKIP"
    assert skipped["reason"] == "llm_inference_cloud_disable_unverified"
    assert calls == []
    allowed = matrix._llm_inference(_cfg(), **kwargs, ollama_server_pid=4242)
    assert allowed["status"] == "PASS"
    assert calls == [(11434, MODEL, 4242)]
