from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from api.main import app
from api.routers import export
from api.services.turn_execution import AgentTurnResult
from tests.security_test_utils import bearer


def _turn_result() -> AgentTurnResult:
    return AgentTurnResult(
        session_id="automation-session",
        turn_id="turn-123",
        request_id="turn-123",
        user_message="請產生報告",
        output={
            "mode": "SRA_REPORT",
            "route": {"mode": "SRA_REPORT"},
            "user_question": "請產生報告",
            "answer": "# 自動化報告\n\n本輪即時產生。",
            "citations": [],
            "session_id": "automation-session",
            "turn_id": "turn-123",
            "request_id": "turn-123",
        },
        trace={"timing": {}},
    )


def test_post_report_word_returns_docx_from_current_turn_without_state_read(monkeypatch, tmp_path):
    monkeypatch.setattr(export, "execute_agent_turn", lambda **kwargs: _turn_result())
    monkeypatch.setattr(
        export.API_STORE,
        "read_raw",
        lambda: (_ for _ in ()).throw(AssertionError("POST must not read state.json")),
    )

    response = TestClient(app).post(
        "/v1/report/word",
        headers={**bearer(monkeypatch,tmp_path,["report:sync"]), "X-Session-Id": "automation-session"},
        json={
            "model": "SRA-Structured Retrieval Agent",
            "messages": [{"role": "user", "content": "請產生報告"}],
            "filename": "monthly-report.docx",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "monthly-report.docx" in response.headers["content-disposition"]
    assert response.headers["x-session-id"] == "automation-session"
    assert response.headers["x-turn-id"] == "turn-123"
    document = Document(BytesIO(response.content))
    assert "本輪即時產生" in "\n".join(p.text for p in document.paragraphs)


def test_post_report_word_rejects_streaming_request(monkeypatch, tmp_path):
    response = TestClient(app).post(
        "/v1/report/word",
        headers=bearer(monkeypatch,tmp_path,["report:sync"]), json={
            "messages": [{"role": "user", "content": "請產生報告"}],
            "stream": True,
        },
    )
    assert response.status_code == 422


def test_report_word_openapi_declares_downloadable_docx_response():
    operation = TestClient(app).get("/openapi.json").json()["paths"]["/v1/report/word"]["post"]

    assert operation["responses"]["200"]["content"] == {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
            "schema": {"type": "string", "format": "binary"}
        }
    }
