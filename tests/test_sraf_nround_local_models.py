"""Local provider wire contract; synthetic HTTP only."""
import json

import pytest

from agent.adaptive_retrieval.coverage_evaluator import CoverageTarget
from agent.adaptive_retrieval.evidence_ledger import PrivateCanonicalEvidence
from api.services import sraf_nround_local_models as mod


def models(endpoint="http://127.0.0.1:11434"):
    return mod.LocalDeepModels(endpoint, "planner:local", "semantic:local", "report:local", 32768)


@pytest.mark.parametrize("endpoint", [
    "https://example.org:443", "http://8.8.8.8:11434", "http://localhost:11434",
    "http://127.0.0.1:11434/?x=1", "http://user@127.0.0.1:11434",
    "http://127.0.0.1:11434/else", "http://127.0.0.1:11434/#",
    "http://169.254.169.254:80", "http://127.0.0.1",
])
def test_endpoint_rejects_nonapproved_forms(endpoint):
    with pytest.raises(mod.DeepModelError):
        models(endpoint)


def test_configuration_no_cloud_or_implicit_context():
    assert models("http://192.168.1.2:11434/").endpoint.endswith(":11434/api/chat")
    assert models("http://[::1]:11434").endpoint == "http://[::1]:11434/api/chat"
    with pytest.raises(mod.DeepModelError):
        mod.LocalDeepModels("http://127.0.0.1:11434", "foo:cloud", "s", "r", 32768)
    with pytest.raises(mod.DeepModelError):
        mod.LocalDeepModels("http://127.0.0.1:11434", "p", "s", "r", 0)


class Response:
    status_code = 200
    def __init__(self, content, *, reason="stop", role="assistant"):
        self.data = json.dumps({"done": True, "done_reason": reason,
                                "message": {"role": role, "content": content}}).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def iter_content(self, **_):
        yield self.data


def wire(monkeypatch, *responses):
    calls = []
    queue = iter(responses)
    class Session:
        trust_env = True
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def post(self, url, **kw):
            assert self.trust_env is False
            calls.append((url, kw))
            return next(queue)
    monkeypatch.setattr(mod.requests, "Session", Session)
    return calls


def test_planner_semantic_and_report_use_explicit_models(monkeypatch):
    calls = wire(monkeypatch, Response('{"action":"stop"}'),
                 Response('{"supported":true}'), Response("報告"))
    m = models()
    assert m.plan("question", system_prompt="system", timeout=12) == '{"action":"stop"}'
    target = CoverageTarget("aspect", "外交")
    evidence = PrivateCanonicalEvidence("外交資料", "2025-01-01", ())
    assert m.assess(target, evidence, timeout=3) is True
    assert m.report("report", system_prompt="system", timeout=10, model="report:local",
                    stage="report", extra_params={"options": {}}) == "報告"
    assert [c[1]["json"]["model"] for c in calls] == ["planner:local", "semantic:local", "report:local"]
    for url, kw in calls:
        assert url == m.endpoint and kw["allow_redirects"] is False
        assert kw["stream"] is True and kw["json"]["stream"] is False
    assert calls[1][1]["timeout"] == (3, 3)
    assert calls[1][1]["json"]["format"] == "json"
    assert "format" not in calls[2][1]["json"]


@pytest.mark.parametrize("raw", ['{"supported":"true"}', '{"supported":1}', '{}',
                                 '{"supported":true,"extra":1}', 'not JSON'])
def test_invalid_semantic_result_is_failure_not_false(monkeypatch, raw):
    wire(monkeypatch, Response(raw))
    with pytest.raises(mod.DeepModelError):
        models().assess(CoverageTarget("entity", "甲"),
                        PrivateCanonicalEvidence("資料", "2025-01-01", ()), timeout=2)


def test_truncation_redirect_overflow_and_report_model_mismatch(monkeypatch):
    redirect = Response("private")
    redirect.status_code = 302
    oversized = Response("x")
    oversized.data = b"x" * 1048577
    calls = wire(monkeypatch, Response("partial", reason="length"), redirect, oversized)
    m = models()
    for _ in range(3):
        with pytest.raises(mod.DeepModelError):
            m.plan("question", system_prompt="system", timeout=2)
    with pytest.raises(mod.DeepModelError):
        m.report("report", system_prompt="system", timeout=2, model="wrong",
                 stage="report", extra_params={"options": {}})
    assert len(calls) == 3
    with pytest.raises(mod.DeepModelError):
        m.plan("中" * 20000, system_prompt="system", timeout=2)
    assert len(calls) == 3
