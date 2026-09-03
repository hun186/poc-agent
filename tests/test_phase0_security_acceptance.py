from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import chat, docs, export, report_jobs, service_keys
from api.routers.editor_dependencies import require_superuser
from api.security.models import AuthPrincipal
from api.security.principal import current_principal, optional_principal, require_scopes
from api.security.scopes import MODEL_INVOKE, MODEL_READ
from api.security.service_key_store import ServiceKeyStore
import api.security.service_key_store as store_module
from api.services.auth_store import AuthUser
from api.services.report_job_store import ReportJob, ReportJobStore
from api.security.signed_urls import sign_resource


def _mutate_key_store(args):
    path, index = args
    item, raw = ServiceKeyStore(path).create(f"worker-{index}", ["model:read"], "pytest")
    return item["key_id"], raw


def _initialize_job_store(path):
    ReportJobStore(path).initialize()


def _legacy_db(path: Path) -> None:
    sql = """CREATE TABLE report_jobs (job_id TEXT PRIMARY KEY,status TEXT NOT NULL,prompt TEXT NOT NULL,filename TEXT,session_id TEXT NOT NULL,model TEXT NOT NULL,options_json TEXT NOT NULL,metadata_json TEXT NOT NULL,idempotency_key TEXT UNIQUE,request_hash TEXT NOT NULL,turn_id TEXT,docx_basename TEXT,error_type TEXT,error_message TEXT,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,updated_at TEXT NOT NULL)"""
    with sqlite3.connect(path) as con:
        con.execute(sql)
        con.execute("INSERT INTO report_jobs(job_id,status,prompt,session_id,model,options_json,metadata_json,idempotency_key,request_hash,created_at,updated_at) VALUES('legacy','queued','p','s','m','{}','{}','key','hash','now','now')")


def test_unified_authentication_and_authorization_denials_are_safely_audited(monkeypatch):
    events = []
    monkeypatch.setattr("api.security.principal.append_audit_event", events.append)
    with pytest.raises(Exception) as malformed:
        optional_principal("Bearer invalid")
    assert malformed.value.status_code == 401
    with pytest.raises(Exception) as missing:
        current_principal(None)
    assert missing.value.status_code == 401
    dependency = require_scopes("model:invoke")
    principal = AuthPrincipal("service", "reader", None, frozenset({"model:read"}), "key-id")
    with pytest.raises(Exception) as denied:
        dependency(principal)
    assert denied.value.status_code == 403
    rendered = json.dumps(events)
    assert [event["action"] for event in events] == [
        "security.authentication_denied", "security.authentication_denied", "security.authorization_denied"
    ]
    assert "Bearer invalid" not in rendered and "Authorization" not in rendered and "token_digest" not in rendered


def test_service_key_http_admin_create_list_revoke_and_audit_no_secret_leak(tmp_path, monkeypatch):
    store = ServiceKeyStore(tmp_path / "keys.json")
    events = []
    monkeypatch.setattr(store_module, "SERVICE_KEY_STORE", store)
    monkeypatch.setattr(service_keys, "append_audit_event", events.append)
    app = FastAPI()
    app.include_router(service_keys.router)
    app.dependency_overrides[require_superuser] = lambda: AuthUser("root", "superuser", "active")
    client = TestClient(app)

    created = client.post("/v1/auth/service-keys", json={"name": "owui", "scopes": ["model:read"]})
    assert created.status_code == 200
    body = created.json(); raw = body.pop("key")
    listed = client.get("/v1/auth/service-keys")
    revoked = client.post(f"/v1/auth/service-keys/{body['key_id']}/revoke")
    assert listed.status_code == revoked.status_code == 200
    non_create_surface = json.dumps({"listed": listed.json(), "revoked": revoked.json(), "audit": events})
    assert raw not in non_create_surface and "token_digest" not in non_create_surface
    assert [event["action"] for event in events] == ["security.service_key_created", "security.service_key_revoked"]
    assert store.resolve(raw) is None

    unknown = client.post("/v1/auth/service-keys", json={"name": "bad", "scopes": ["unknown:scope"]})
    assert unknown.status_code == 422


def test_service_key_cannot_satisfy_editor_superuser_dependency(tmp_path, monkeypatch):
    store = ServiceKeyStore(tmp_path / "keys.json")
    _, raw = store.create("service", ["model:read"], "pytest")
    monkeypatch.setattr(store_module, "SERVICE_KEY_STORE", store)
    app = FastAPI(); app.include_router(service_keys.router)
    response = TestClient(app).get("/v1/auth/service-keys", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 401


def test_non_superuser_cannot_administer_service_keys(monkeypatch):
    app = FastAPI(); app.include_router(service_keys.router)
    app.dependency_overrides[require_superuser] = lambda: (_ for _ in ()).throw(Exception("override must be replaced"))
    # Exercise the real RBAC dependency directly with an authenticated, insufficient user.
    app.dependency_overrides.clear()
    from api.routers.editor_dependencies import require_role
    dependency = require_role("superuser", "require_superuser", "denied")
    monkeypatch.setattr("api.routers.editor_dependencies.append_audit_event", lambda event: None)
    with pytest.raises(Exception) as denied:
        dependency(AuthUser("reader", "data_reader", "active"))
    assert denied.value.status_code == 403


def test_cross_process_service_key_mutation_is_atomic_and_secret_free(tmp_path):
    path = tmp_path / "shared.json"
    count = 12
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=6, mp_context=context) as pool:
        results = list(pool.map(_mutate_key_store, [(str(path), i) for i in range(count)]))
    key_ids = [item[0] for item in results]
    raw_keys = [item[1] for item in results]
    persisted = path.read_text(encoding="utf-8")
    parsed = json.loads(persisted)
    assert len(parsed["keys"]) == count
    assert len(set(key_ids)) == count
    assert all(raw not in persisted for raw in raw_keys)
    assert all("token_digest" in item and "key" not in item for item in parsed["keys"])


@pytest.mark.parametrize("legacy", [False, True], ids=["fresh", "legacy-v0"])
def test_concurrent_report_job_initialization_converges_to_canonical_schema(tmp_path, legacy):
    path = tmp_path / "jobs.db"
    if legacy:
        _legacy_db(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_initialize_job_store, [path] * 12))
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"report_jobs_new", "report_jobs_old"} & tables
        index = con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_report_jobs_owner_idempotency'").fetchone()
        assert index and "WHERE idempotency_key IS NOT NULL" in index[0]
        if legacy:
            assert con.execute("SELECT owner_kind, owner_id FROM report_jobs WHERE job_id='legacy'").fetchone() == (None, None)


def _signed_client(monkeypatch):
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "x" * 32)
    monkeypatch.setattr(docs, "_get_doc_source_or_404", lambda doc_id: {"uuid": doc_id, "title": "t", "full_text": "body"})
    app = FastAPI(); app.include_router(docs.router); app.include_router(export.router)
    return TestClient(app)


@pytest.mark.parametrize("query", [
    "sig={sig}&sig={sig}", "format=json&format=json&download=0&text_layer=reference&sig={sig}",
    "format=json&download=0&download=0&text_layer=reference&sig={sig}",
    "format=json&download=0&text_layer=reference&text_layer=reference&sig={sig}",
    "format=json&download=0&text_layer=reference&extra=1&sig={sig}",
])
def test_signed_document_capability_rejects_duplicate_or_extra_query(monkeypatch, query):
    client = _signed_client(monkeypatch)
    if "format=" in query:
        sig = sign_resource("doc_fulltext", doc_id="doc", format="json", download="0", text_layer="reference")
        url = "/v1/docs/doc/fulltext?" + query.format(sig=sig)
    else:
        sig = sign_resource("doc_detail", doc_id="doc")
        url = "/v1/docs/doc?" + query.format(sig=sig)
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("download", ["false", "true", "00", "2"])
def test_signed_download_requires_canonical_zero_or_one(monkeypatch, download):
    client = _signed_client(monkeypatch)
    sig = sign_resource("doc_fulltext", doc_id="doc", format="json", download="0", text_layer="reference")
    assert client.get("/v1/docs/doc/fulltext", params={"format":"json", "download":download, "text_layer":"reference", "sig":sig}).status_code == 401


def test_invalid_authorization_never_falls_back_to_valid_capability(monkeypatch):
    client = _signed_client(monkeypatch)
    sig = sign_resource("doc_detail", doc_id="doc")
    response = client.get("/v1/docs/doc", params={"sig": sig}, headers={"Authorization":"Bearer invalid"})
    assert response.status_code == 401


def test_capability_is_validated_before_resource_lookup_and_substitution_fails(monkeypatch):
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "x" * 32)
    looked_up = []
    monkeypatch.setattr(docs, "_get_doc_source_or_404", lambda doc_id: looked_up.append(doc_id) or {"uuid":doc_id})
    app = FastAPI(); app.include_router(docs.router); client = TestClient(app)
    detail_sig = sign_resource("doc_detail", doc_id="a")
    assert client.get("/v1/docs/b", params={"sig": detail_sig}).status_code == 401
    fulltext_sig = sign_resource("doc_fulltext", doc_id="a", format="json", download="0", text_layer="reference")
    assert client.get("/v1/docs/a", params={"sig": fulltext_sig}).status_code == 401
    assert looked_up == []


def test_successful_signed_resources_have_security_headers(monkeypatch):
    client = _signed_client(monkeypatch)
    detail = client.get("/v1/docs/doc", params={"sig": sign_resource("doc_detail", doc_id="doc")})
    fulltext = client.get("/v1/docs/doc/fulltext", params={"format":"json", "download":"0", "text_layer":"reference", "sig":sign_resource("doc_fulltext", doc_id="doc", format="json", download="0", text_layer="reference")})
    for response in (detail, fulltext):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_admin_cross_owner_report_job_access_is_audited(monkeypatch):
    events = []
    job = ReportJob(
        job_id="job-1", status="queued", prompt="p", filename=None, session_id="s", model="m",
        options={}, metadata={}, idempotency_key=None, request_hash="h", owner_kind="service", owner_id="owner",
    )
    principal = AuthPrincipal("service", "administrator", None, frozenset({"report:job:admin", "report:job:read"}), "admin-id")
    monkeypatch.setattr(report_jobs, "append_audit_event", events.append)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(report_job_store=SimpleNamespace(get=lambda job_id: job))))
    response = report_jobs.status("job-1", request, principal)
    assert response["job_id"] == "job-1"
    assert events == [{
        "action": "security.report_job_admin_cross_owner_access", "principal_kind": "service",
        "subject": "administrator", "job_id": "job-1", "operation": "read",
    }]


def test_fast_openwebui_scope_matrix_uses_actual_routes(tmp_path, monkeypatch):
    store = ServiceKeyStore(tmp_path / "matrix.json")
    monkeypatch.setattr(store_module, "SERVICE_KEY_STORE", store)
    _, read_raw = store.create("reader", [MODEL_READ], "pytest")
    invoke_item, invoke_raw = store.create("invoker", [MODEL_INVOKE], "pytest")
    _, owui_raw = store.create("openwebui", [MODEL_READ, MODEL_INVOKE], "pytest")
    _, report_raw = store.create("report", ["report:job:create"], "pytest")

    from api.services.turn_execution import AgentTurnResult
    monkeypatch.setattr(chat, "execute_agent_turn", lambda **kwargs: AgentTurnResult(
        session_id="scope-session", turn_id="scope-turn", request_id="scope-request",
        user_message="hello", output={"mode":"PURE_LLM", "route":"PURE_LLM", "answer":"ok"}, trace=kwargs["trace"],
    ))
    monkeypatch.setattr(chat, "render_markdown", lambda output, request, session: "ok")
    monkeypatch.setattr(chat, "save_session_and_memory", lambda **kwargs: None)
    monkeypatch.setattr(chat, "save_trace", lambda trace: None)
    monkeypatch.setattr(chat.API_STORE, "save_all_throttled", lambda **kwargs: None)
    app = FastAPI(); app.include_router(chat.router); app.include_router(report_jobs.router)
    client = TestClient(app)
    bearer = lambda raw: {"Authorization": f"Bearer {raw}"}
    payload = {"model":"SRA-Structured Retrieval Agent", "messages":[{"role":"user", "content":"hello"}]}

    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization":"Bearer invalid"}).status_code == 401
    assert client.get("/v1/models", headers=bearer(read_raw)).status_code == 200
    assert client.get("/v1/models", headers=bearer(invoke_raw)).status_code == 403
    assert client.post("/v1/chat/completions", headers=bearer(read_raw), json=payload).status_code == 403
    assert client.get("/v1/models", headers=bearer(owui_raw)).status_code == 200
    assert client.post("/v1/chat/completions", headers=bearer(owui_raw), json=payload).status_code == 200
    assert client.post("/v1/report/jobs", headers=bearer(owui_raw), json={"prompt":"p"}).status_code == 403
    assert client.post("/v1/chat/completions", headers=bearer(report_raw), json=payload).status_code == 403
    for spoofed in ("X-OpenWebUI-Chat-Id", "X-Session-Id"):
        assert client.get("/v1/models", headers={spoofed:"spoof"}).status_code == 401
    store.revoke(invoke_item["key_id"], "pytest")
    assert client.post("/v1/chat/completions", headers=bearer(invoke_raw), json=payload).status_code == 401


def test_legacy_word_capability_rejects_duplicate_and_session_turn_substitution(monkeypatch):
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "x" * 32)
    looked_up = []
    monkeypatch.setattr(export.API_STORE, "read_raw", lambda: looked_up.append(True) or {})
    app = FastAPI(); app.include_router(export.router); client = TestClient(app)
    sig = sign_resource("legacy_word", session_id="session-a", turn_id="turn-a")
    cases = [
        f"session_id=session-a&session_id=session-a&turn_id=turn-a&sig={sig}",
        f"session_id=session-a&turn_id=turn-a&turn_id=turn-a&sig={sig}",
        f"session_id=session-a&turn_id=turn-a&sig={sig}&sig={sig}",
        f"session_id=session-b&turn_id=turn-a&sig={sig}",
        f"session_id=session-a&turn_id=turn-b&sig={sig}",
        f"session_id=session-a&turn_id=turn-a&extra=1&sig={sig}",
    ]
    for query in cases:
        assert client.get("/v1/export/word?" + query).status_code == 401
    assert looked_up == []


def test_production_signing_secret_fails_closed_and_valid_secret_passes(monkeypatch):
    import api.security.signed_urls as signed_urls
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SRA_SIGNED_URL_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        signed_urls.validate_signing_config()
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "short")
    with pytest.raises(RuntimeError):
        signed_urls.validate_signing_config()
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "v" * 32)
    signed_urls.validate_signing_config()


def test_nonproduction_signing_fallback_warns_once_without_secret(monkeypatch):
    import api.security.signed_urls as signed_urls
    monkeypatch.setattr(signed_urls, "_fallback_warned", False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SRA_SIGNED_URL_SECRET", raising=False)
    with pytest.warns(RuntimeWarning) as caught:
        signed_urls.validate_signing_config(); signed_urls.validate_signing_config()
    assert len(caught) == 1
    message = str(caught[0].message)
    assert "fallback" in message and "secret-change-me" not in message
