from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routers.editor_dependencies import current_user, require_db_operator, require_superuser
from api.services.auth_store import AuthUser
from sra_api.routers.requirements import requirement_service, router
from data_ingestion.requirements.service import RequirementImportService
from tests.requirement_test_support import MemoryStore

def app(role="superuser"):
    value=FastAPI(); value.include_router(router); store=MemoryStore(); service=RequirementImportService(store); user=AuthUser(username="u",role=role,status="active")
    value.dependency_overrides[requirement_service]=lambda:service; value.dependency_overrides[current_user]=lambda:user; value.dependency_overrides[require_db_operator]=lambda:user; value.dependency_overrides[require_superuser]=lambda:user; return value
def test_management_crud_and_safe_models():
    client=TestClient(app()); response=client.post("/v1/requirement-import-profiles",json={"name":"p","description":"d","enabled":True}); assert response.status_code==201; pid=response.json()["profile_id"]
    source=client.post("/v1/requirement-sources",json={"name":"s","source_type":"sql_query","source_mode":"authoritative_snapshot","source_config":{"connection_ref":"safe","query_ref":"reviewed"},"import_profile_id":pid,"enabled":True}); assert source.status_code==201 and "password" not in source.text.casefold()
    assert client.get("/v1/requirement-sources").status_code==200
def test_disabled_dependency_is_503():
    value=FastAPI(); value.include_router(router)
    user=AuthUser(username="u",role="superuser",status="active"); value.dependency_overrides[current_user]=lambda:user
    assert TestClient(value).get("/v1/requirement-sources").status_code==503
