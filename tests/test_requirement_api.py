from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routers.editor_dependencies import current_user, require_db_operator, require_superuser
from api.services.auth_store import AuthUser
from sra_api.routers.requirements import requirement_service, router
from data_ingestion.requirements.service import RequirementImportService
from tests.requirement_test_support import MemoryStore

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

def test_operator_can_create_drafts_but_cannot_enable_or_approve():
    client=TestClient(app("db_operator"))
    profile=client.post("/v1/requirement-import-profiles",json={"name":"p","description":"d"})
    assert profile.status_code == 201
    pid=profile.json()["profile_id"]
    assert client.patch(f"/v1/requirement-import-profiles/{pid}",json={"enabled":True}).status_code == 403
    assert client.post(f"/v1/requirement-import-profiles/{pid}/versions/1/approve").status_code == 403
    source=client.post("/v1/requirement-sources",json={"name":"s","source_type":"manual_upload","source_mode":"authoritative_snapshot","source_config":{},"import_profile_id":pid})
    assert source.status_code == 201
    assert client.patch(f"/v1/requirement-sources/{source.json()['source_id']}",json={"enabled":True}).status_code == 403

def test_safe_infrastructure_error_mapping_does_not_leak_driver_detail():
    class FailingStore(MemoryStore):
        def list_sources(self): raise RuntimeError("persistence_error") from RuntimeError("PWD=secret")
    value=app(); value.dependency_overrides[requirement_service]=lambda:RequirementImportService(FailingStore())
    # List routes now also need the common safe boundary.
    response=TestClient(value).get("/v1/requirement-sources")
    assert response.status_code == 500
    assert response.json() == {"detail":{"code":"persistence_error"}}
