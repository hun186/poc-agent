from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from data_ingestion.excel_to_sql.sql_utils import quote_ident, quote_object_path
from data_ingestion.excel_to_sql.task_configs import create_task_config
from data_ingestion.excel_to_sql.user_import_storage import _record_path
from portable_auth_pack.fastapi_auth_pack.dependencies import bearer_token as portable_bearer_token
from api.routers import chat, docs, export
from api.routers.editor_dependencies import bearer_token
from api.routers.editor_dependencies import scope_resource_id
from api.services.auth_store import AuthUser


ROUTERS = (chat.router, docs.router, export.router)


def _route(path: str, method: str):
    return next(
        route
        for router in ROUTERS
        for route in router.routes
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/v1/models", "GET"),
        ("/v1/chat/completions", "POST"),
        ("/v1/docs/{doc_id}", "GET"),
        ("/v1/docs/{doc_id}/fulltext", "GET"),
        ("/v1/export/word", "GET"),
    ],
)
def test_openwebui_agent_routes_remain_public(path: str, method: str) -> None:
    route = _route(path, method)
    assert not route.dependant.dependencies


def test_health_check_remains_public() -> None:
    assert not _route("/healthz", "GET").dependant.dependencies


@pytest.fixture
def openwebui_client() -> TestClient:
    app = FastAPI()
    for router in ROUTERS:
        app.include_router(router)
    return TestClient(app)


def test_openwebui_can_open_and_download_cited_document_without_editor_token(
    monkeypatch, openwebui_client: TestClient
) -> None:
    document = {
        "uuid": "doc-1",
        "title": "資料庫文件",
        "full_text": "文件全文內容",
    }
    monkeypatch.setattr(docs, "_get_doc_source_or_404", lambda _doc_id: document)

    detail = openwebui_client.get("/v1/docs/doc-1")
    fulltext = openwebui_client.get("/v1/docs/doc-1/fulltext")
    download = openwebui_client.get(
        "/v1/docs/doc-1/fulltext", params={"format": "txt", "download": "true"}
    )

    assert detail.status_code == 200
    assert detail.json()["uuid"] == "doc-1"
    assert fulltext.status_code == 200
    assert fulltext.json()["full_text"] == "文件全文內容"
    assert download.status_code == 200
    assert download.text == "文件全文內容"
    assert download.headers["content-disposition"].startswith("attachment;")


def test_openwebui_can_download_word_without_editor_token(
    monkeypatch, openwebui_client: TestClient
) -> None:
    monkeypatch.setattr(
        export.API_STORE,
        "read_raw",
        lambda: {"structured_history": {"session-1": {"turn-1": {"mode": "PURE_LLM"}}}},
    )
    monkeypatch.setattr(
        export.ExportWordService,
        "build_docx_bytes",
        lambda _self, _out, filename: (b"docx-content", filename),
    )

    response = openwebui_client.get(
        "/v1/export/word", params={"session_id": "session-1", "turn_id": "turn-1"}
    )

    assert response.status_code == 200
    assert response.content == b"docx-content"
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["content-disposition"].startswith("attachment;")


def test_legacy_session_scope_import_is_a_noop_for_mixed_deployments() -> None:
    user = AuthUser(username="legacy", role="data_reader", status="active")
    assert scope_resource_id(user, "openwebui-session") == "openwebui-session"


def test_chat_support_uses_package_relative_import_without_router_recursion() -> None:
    source = Path("sra_api/routers/chat.py").read_text(encoding="utf-8")
    assert "from .chat_support import (" in source
    assert "from sra_api.routers.chat_support import (" not in source
    assert "scope_resource_id" not in source


@pytest.mark.parametrize("parser", [bearer_token, portable_bearer_token])
@pytest.mark.parametrize("value", [None, "", "Basic abc", "Bearer", "Bearer ", "Bearer abc def"])
def test_bearer_parser_rejects_malformed_values(parser, value: str | None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        parser(value)
    assert exc_info.value.status_code == 401


def test_sql_identifiers_are_quoted_and_structurally_validated() -> None:
    assert quote_ident("name] DROP TABLE users;--") == "[name]] DROP TABLE users;--]"
    assert quote_object_path("dbo.records") == "[dbo].[records]"
    for invalid in ("dbo..records", ".records", "server.database.dbo.records", "bad\x00name"):
        with pytest.raises(ValueError):
            quote_object_path(invalid)


def _task_payload(filename: str) -> dict:
    return {
        "filename": filename,
        "task_name": "Owned task",
        "db_server": "sql.local",
        "db_database": "OpsDb",
        "db_user": "operator",
        "db_password": "not-a-real-secret",
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [{"source_column": "A", "dest_field": "a"}],
    }


def test_task_filename_does_not_authorize_overwriting_another_owner(tmp_path) -> None:
    payload = _task_payload("shared-name.json")
    create_task_config(payload, actor="alice", root=tmp_path)

    with pytest.raises(PermissionError, match="只能覆寫自己建立"):
        create_task_config(payload, actor="bob", root=tmp_path, overwrite=True)

    overwritten = create_task_config(
        payload, actor="admin", root=tmp_path, overwrite=True, is_superuser=True
    )
    assert overwritten["created_by"] == "admin"


def test_import_record_filename_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="ID 格式錯誤"):
        _record_path("../../another-users-record")


def test_config_directory_cannot_be_changed_by_request() -> None:
    from api.routers.excel_to_sql import _ensure_default_config_dir

    with pytest.raises(HTTPException) as exc_info:
        _ensure_default_config_dir("config")
    assert exc_info.value.status_code == 403
