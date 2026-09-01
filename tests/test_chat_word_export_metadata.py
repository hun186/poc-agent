from fastapi.testclient import TestClient

from api.main import app
from api.routers import chat
from api.services.turn_execution import AgentTurnResult


def test_chat_completion_exposes_word_export_metadata(monkeypatch):
    result = AgentTurnResult(
        session_id="chat-session",
        turn_id="chat-turn",
        request_id="chat-turn",
        user_message="問題",
        output={"mode": "SRA_REPORT", "answer": "回答", "citations": []},
        trace={"timing": {}},
    )
    monkeypatch.setattr(chat, "execute_agent_turn", lambda **kwargs: result)
    monkeypatch.setattr(chat, "save_session_and_memory", lambda **kwargs: None)
    monkeypatch.setattr(chat.API_STORE, "save_all_throttled", lambda **kwargs: None)
    monkeypatch.setattr(chat, "save_trace", lambda trace: None)

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"X-Session-Id": "chat-session"},
        json={"messages": [{"role": "user", "content": "問題"}]},
    )

    assert response.status_code == 200
    metadata = response.json()["choices"][0]["message"]["context"]["word_export"]
    assert metadata["method"] == "GET"
    assert metadata["session_id"] == "chat-session"
    assert metadata["turn_id"] == "chat-turn"
    assert metadata["url"].endswith(
        "/v1/export/word?session_id=chat-session&turn_id=chat-turn"
    )
