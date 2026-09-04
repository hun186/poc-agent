from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routers.editor_dependencies import current_user, require_db_operator, require_superuser
from api.services.auth_store import AuthUser
from sra_api.routers.requirements import requirement_service, router
from data_ingestion.requirements.service import RequirementImportService
from tests.requirement_test_support import MemoryStore, sample_profile, sample_row
import json

def app(role="superuser"):
    value=FastAPI(); value.include_router(router); store=MemoryStore(); service=RequirementImportService(store); user=AuthUser(username="u",role=role,status="active")
    value.dependency_overrides[requirement_service]=lambda:service; value.dependency_overrides[current_user]=lambda:user; return value
def test_management_crud_and_safe_models():
    client=TestClient(app()); response=client.post("/v1/requirement-import-profiles",json={"name":"p","description":"d","enabled":True}); assert response.status_code==201; pid=response.json()["profile_id"]
    source=client.post("/v1/requirement-sources",json={"name":"s","source_type":"sql_query","source_mode":"authoritative_snapshot","source_config":{"connection_ref":"safe","query_ref":"reviewed"},"import_profile_id":pid,"enabled":True}); assert source.status_code==201 and "password" not in source.text.casefold()
    assert client.get("/v1/requirement-sources").status_code==200
def test_disabled_dependency_is_503():
    value=FastAPI(); value.include_router(router)
    user=AuthUser(username="u",role="superuser",status="active"); value.dependency_overrides[current_user]=lambda:user
    assert TestClient(value).get("/v1/requirement-sources").status_code==503

def test_unauthenticated_and_underprivileged_requests_use_dependency_rbac():
    unauth=FastAPI(); unauth.include_router(router); unauth.dependency_overrides[requirement_service]=lambda:RequirementImportService(MemoryStore())
    assert TestClient(unauth).get("/v1/requirement-sources").status_code == 401
    reader=TestClient(app("data_reader"))
    assert reader.get("/v1/requirement-sources").status_code == 200
    assert reader.post("/v1/requirement-import-profiles",json={"name":"p","description":"d"}).status_code == 403
    protected = [
        ("post", "/v1/requirement-sources", {"json": {"name":"s","source_type":"manual_upload","source_mode":"authoritative_snapshot","source_config":{},"import_profile_id":"p"}}),
        ("patch", "/v1/requirement-sources/s", {"json": {"name":"x"}}),
        ("post", "/v1/requirement-import-profiles/p/versions", {"json": {"profile": sample_profile()}}),
        ("post", "/v1/requirement-sources/s/preview", {}),
        ("post", "/v1/requirement-sources/s/import", {}),
    ]
    for method,path,kwargs in protected:
        assert getattr(reader,method)(path,**kwargs).status_code == 403

def test_operator_can_create_drafts_and_preview_but_cannot_enable_or_approve():
    client=TestClient(app("db_operator"))
    profile=client.post("/v1/requirement-import-profiles",json={"name":"p","description":"d"})
    assert profile.status_code == 201
    pid=profile.json()["profile_id"]
    assert client.patch(f"/v1/requirement-import-profiles/{pid}",json={"enabled":True}).status_code == 403
    assert client.post(f"/v1/requirement-import-profiles/{pid}/versions/1/approve").status_code == 403
    source=client.post("/v1/requirement-sources",json={"name":"s","source_type":"manual_upload","source_mode":"authoritative_snapshot","source_config":{},"import_profile_id":pid})
    assert source.status_code == 201
    assert client.patch(f"/v1/requirement-sources/{source.json()['source_id']}",json={"enabled":True}).status_code == 403
    version=client.post(f"/v1/requirement-import-profiles/{pid}/versions",json={"profile":sample_profile()})
    assert version.status_code == 201 and version.json()["status"] == "draft"
    preview=client.post(f"/v1/requirement-sources/{source.json()['source_id']}/preview?profile_version_id={version.json()['profile_version_id']}",files={"file":("x.json",json.dumps([sample_row()]),"application/json")})
    assert preview.status_code == 200

def test_superuser_can_enable_and_approve_profile_configuration():
    client=TestClient(app("superuser"))
    profile=client.post("/v1/requirement-import-profiles",json={"name":"p","description":"d"}).json(); pid=profile["profile_id"]
    version=client.post(f"/v1/requirement-import-profiles/{pid}/versions",json={"profile":sample_profile()}).json()
    assert client.post(f"/v1/requirement-import-profiles/{pid}/versions/{version['version_number']}/approve").status_code == 200
    assert client.patch(f"/v1/requirement-import-profiles/{pid}",json={"enabled":True}).status_code == 200
    source=client.post("/v1/requirement-sources",json={"name":"s","source_type":"manual_upload","source_mode":"authoritative_snapshot","source_config":{},"import_profile_id":pid}).json()
    assert client.patch(f"/v1/requirement-sources/{source['source_id']}",json={"enabled":True}).status_code == 200

def test_operator_activation_denials_use_canonical_authz_audit(monkeypatch):
    events=[]
    monkeypatch.setattr("api.routers.editor_dependencies.append_audit_event",events.append)
    client=TestClient(app("db_operator"))
    response=client.post("/v1/requirement-import-profiles",json={"name":"p","description":"d","enabled":True})
    assert response.status_code == 403
    assert events and events[-1]["action"] == "authz.denied"

def test_multipart_upload_is_confined_to_manual_upload_sources():
    value=app("superuser"); service=value.dependency_overrides[requirement_service](); store=service.store
    profile=store.create_profile("p","","admin",enabled=True); version=store.create_profile_version(profile["profile_id"],sample_profile(),"admin"); store.approve_profile_version(profile["profile_id"],1,"admin")
    manual=store.create_source("manual","manual_upload","authoritative_snapshot",{},profile["profile_id"],"admin",enabled=True)
    client=TestClient(value); upload={"file":("x.json",json.dumps([sample_row()]),"application/json")}
    assert client.post(f"/v1/requirement-sources/{manual['source_id']}/preview",files=upload).status_code == 200
    for kind,config in (("file_path",{"path":"x.json"}),("sql_query",{"connection_ref":"safe","query_ref":"reviewed"})):
        source=store.create_source(kind,kind,"authoritative_snapshot",config,profile["profile_id"],"admin",enabled=True)
        response=client.post(f"/v1/requirement-sources/{source['source_id']}/preview",files=upload)
        assert response.status_code == 400 and response.json()["detail"]["code"] == "upload_not_allowed"

def test_http_error_taxonomy_matrix():
    for code,status in (("sql_read_error",503),("persistence_error",500),("stale_source_version",409),("source_version_anomaly",409)):
        class FailingStore(MemoryStore):
            def list_sources(self): raise RuntimeError(code) from RuntimeError("DRIVER=secret;PWD=hidden")
        value=app(); value.dependency_overrides[requirement_service]=lambda store=FailingStore():RequirementImportService(store)
        response=TestClient(value).get("/v1/requirement-sources")
        assert response.status_code == status and response.json() == {"detail":{"code":code}}
        assert "secret" not in response.text and "hidden" not in response.text

def test_unknown_http_error_is_safe_internal_failure():
    class FailingStore(MemoryStore):
        def list_sources(self): raise RuntimeError("ODBC DRIVER=secret;PWD=hidden")
    value=app(); value.dependency_overrides[requirement_service]=lambda:RequirementImportService(FailingStore())
    response=TestClient(value).get("/v1/requirement-sources")
    assert response.status_code == 500 and response.json() == {"detail":{"code":"persistence_error"}}

def test_safe_infrastructure_error_mapping_does_not_leak_driver_detail():
    class FailingStore(MemoryStore):
        def list_sources(self): raise RuntimeError("persistence_error") from RuntimeError("PWD=secret")
    value=app(); value.dependency_overrides[requirement_service]=lambda:RequirementImportService(FailingStore())
    # List routes now also need the common safe boundary.
    response=TestClient(value).get("/v1/requirement-sources")
    assert response.status_code == 500
    assert response.json() == {"detail":{"code":"persistence_error"}}
