from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.editor_dependencies import current_user
from api.services.auth_store import AuthUser
from requirement_scheduler.service import ScheduleService
from sra_api.routers.requirement_schedules import router, schedule_service


class Store:
    def __init__(self): self.data = {}; self.version = 0; self.product_owned = False
    def list_schedules(self, **filters):
        rows = list(self.data.values())
        if filters.get("enabled") is not None: rows = [row for row in rows if row["enabled"] == filters["enabled"]]
        if filters.get("requirement_set_id") is not None: rows = [row for row in rows if row["requirement_set_id"] == filters["requirement_set_id"]]
        return rows[filters.get("offset", 0):][:filters.get("limit", 50)]
    def get_schedule(self, sid):
        if sid not in self.data: raise KeyError("schedule_not_found")
        return self.data[sid]
    def create_schedule(self, name, requirement_set_id, actor):
        self.data["s"] = {"schedule_id":"s","name":name,"requirement_set_id":requirement_set_id,"enabled":False,"next_run_at":None}; return self.data["s"]
    def rename_schedule(self, sid, name, actor): self.data[sid]["name"] = name; return self.data[sid]
    def create_version(self, schedule_id, config, actor): self.version += 1; return {"schedule_version_id":f"v{self.version}","version_number":self.version,"status":"draft"}
    def approve_version(self, **kw): return {"status":"approved","version_number":kw["version_number"]}
    def is_product_owned_schedule(self, schedule_id): return self.product_owned
    def set_enabled(self, **kw): self.data[kw["schedule_id"]]["enabled"] = kw["enabled"]; return self.data[kw["schedule_id"]]


def app(role=None, product_owned=False):
    value=FastAPI(); value.include_router(router); store=Store(); store.product_owned=product_owned; service=ScheduleService(store); value.dependency_overrides[schedule_service]=lambda:service
    if role: value.dependency_overrides[current_user]=lambda:AuthUser(username="u",role=role,status="active")
    return value


def test_auth_and_control_plane_roles():
    assert TestClient(app()).get("/v1/requirement-schedules").status_code == 401
    reader=TestClient(app("data_reader")); assert reader.get("/v1/requirement-schedules").status_code == 200; assert reader.post("/v1/requirement-schedules",json={"name":"x","requirement_set_id":"set"}).status_code == 403
    operator=TestClient(app("db_operator")); assert operator.post("/v1/requirement-schedules",json={"name":"x","requirement_set_id":"set"}).status_code == 201
    assert operator.patch("/v1/requirement-schedules/s",json={"name":"renamed"}).status_code == 200
    body={"timezone":"UTC","recurrence":{"kind":"daily","local_time":"09:00:00"},"run_policy":"all_active","model":"m"}
    assert operator.post("/v1/requirement-schedules/s/versions",json=body).status_code == 201
    assert operator.post("/v1/requirement-schedules/s/versions/1/approve").status_code == 403
    assert operator.patch("/v1/requirement-schedules/s",json={"enabled":True}).status_code == 403
    assert not any("trigger" in getattr(route, "path", "") or "word" in getattr(route, "path", "") for route in app("superuser").routes)


def test_filters_superuser_lifecycle_and_success_denial_audits(monkeypatch):
    events=[]
    monkeypatch.setattr("api.routers.editor_dependencies.append_audit_event", events.append)
    reader=TestClient(app("data_reader"))
    assert reader.post("/v1/requirement-schedules",json={"name":"x","requirement_set_id":"set"}).status_code==403
    assert any(event["action"]=="authz.denied" for event in events)
    events.clear(); client=TestClient(app("superuser"))
    assert client.post("/v1/requirement-schedules",json={"name":"x","requirement_set_id":"set"}).status_code==201
    body={"timezone":"UTC","recurrence":{"kind":"daily","local_time":"09:00:00"},"run_policy":"all_active","model":"m"}
    assert client.post("/v1/requirement-schedules/s/versions",json=body).status_code==201
    assert client.post("/v1/requirement-schedules/s/versions/1/approve").status_code==200
    assert client.patch("/v1/requirement-schedules/s",json={"enabled":True}).status_code==200
    assert client.patch("/v1/requirement-schedules/s",json={"enabled":False}).status_code==200
    assert client.get("/v1/requirement-schedules?enabled=false&requirement_set_id=set&limit=10&offset=0").status_code==200
    # Successful lifecycle evidence is authoritative in the SQL outbox, not a
    # best-effort route-level filesystem append. Denials remain direct JSONL.
    assert events == []



def test_product_owned_schedule_low_level_approval_is_rejected():
    client = TestClient(app("superuser", product_owned=True))

    response = client.post(
        "/v1/requirement-schedules/s/versions/1/approve"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "requirement_product_owned_schedule"
