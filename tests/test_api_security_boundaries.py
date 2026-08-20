from __future__ import annotations

import pytest
from fastapi import HTTPException

from data_ingestion.excel_to_sql.sql_utils import quote_ident, quote_object_path
from data_ingestion.excel_to_sql.task_configs import create_task_config
from data_ingestion.excel_to_sql.user_import_storage import _record_path
from portable_auth_pack.fastapi_auth_pack.dependencies import bearer_token as portable_bearer_token
from sra_api.routers import chat, docs, export
from sra_api.routers.editor_dependencies import bearer_token, scope_resource_id
from sra_api.services.auth_store import AuthUser


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
def test_sensitive_api_routes_require_authentication(path: str, method: str) -> None:
    route = _route(path, method)
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert any(
        call.__name__ == "current_user" and call.__module__.endswith("routers.editor_dependencies")
        for call in dependency_calls
    )


def test_health_check_remains_public() -> None:
    assert not _route("/healthz", "GET").dependant.dependencies


@pytest.mark.parametrize("parser", [bearer_token, portable_bearer_token])
@pytest.mark.parametrize("value", [None, "", "Basic abc", "Bearer", "Bearer ", "Bearer abc def"])
def test_bearer_parser_rejects_malformed_values(parser, value: str | None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        parser(value)
    assert exc_info.value.status_code == 401


def test_session_resources_are_scoped_per_user_and_idempotent() -> None:
    alice = AuthUser(username="alice", role="data_reader", status="active")
    bob = AuthUser(username="bob", role="data_reader", status="active")
    alice_key = scope_resource_id(alice, "conversation-1")
    assert alice_key != scope_resource_id(bob, "conversation-1")
    assert scope_resource_id(alice, alice_key) == alice_key
    assert scope_resource_id(bob, alice_key) != alice_key


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
