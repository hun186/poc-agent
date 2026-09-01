from types import SimpleNamespace

from api.services import turn_execution
from api.services.sessions import ChatMessage


def test_execute_agent_turn_returns_current_structured_output_with_ids(monkeypatch):
    captured = {}

    def fake_answer(**kwargs):
        captured.update(kwargs)
        return {"mode": "SRA_REPORT", "answer": "ok"}

    monkeypatch.setattr(turn_execution, "answer_with_routing", fake_answer)
    monkeypatch.setattr(turn_execution, "save_structured_snapshot", lambda *args: None)
    monkeypatch.setattr(turn_execution, "get_sessions", lambda: {})
    monkeypatch.setattr(turn_execution, "get_last_structured", lambda: {})
    monkeypatch.setattr(turn_execution, "get_memory", lambda: {})

    payload = SimpleNamespace(
        messages=[ChatMessage(role="user", content="本輪問題")],
        model="model",
    )
    request = SimpleNamespace(headers={"x-session-id": "session-1"})
    result = turn_execution.execute_agent_turn(
        payload=payload,
        request=request,
        request_id="request-1",
    )

    assert result.output["session_id"] == "session-1"
    assert result.output["turn_id"] == "request-1"
    assert result.output["request_id"] == "request-1"
    assert captured["user_msg"] == "本輪問題"
    assert captured["session_id"] == "session-1"
    assert result.output is not turn_execution.get_last_structured()


def test_execute_agent_turn_accepts_explicit_session_without_http_request(monkeypatch):
    captured = {}
    monkeypatch.setattr(turn_execution, "answer_with_routing", lambda **kw: captured.update(kw) or {"mode": "SRA_REPORT", "answer": "ok"})
    monkeypatch.setattr(turn_execution, "save_structured_snapshot", lambda *args: None)
    monkeypatch.setattr(turn_execution, "get_sessions", lambda: {})
    monkeypatch.setattr(turn_execution, "get_last_structured", lambda: {})
    monkeypatch.setattr(turn_execution, "get_memory", lambda: {})
    payload = SimpleNamespace(messages=[ChatMessage(role="user", content="job prompt")], model="model")

    result = turn_execution.execute_agent_turn(payload=payload, request=None, session_id="job-session", request_id="request-2")

    assert result.session_id == "job-session"
    assert captured["session_id"] == "job-session"
