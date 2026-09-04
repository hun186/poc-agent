from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.editor_dependencies import current_user
from api.services.auth_store import AuthUser
from requirement_scheduler.service import ScheduleService
from sra_api.routers.requirement_schedules import router, schedule_service


class Store:
    def __init__(self): self.data = {}; self.version = 0
    def list_schedules(self): return list(self.data.values())
    def get_schedule(self, sid):
        if sid not in self.data: raise KeyError("schedule_not_found")
        return self.data[sid]
    def create_schedule(self, name, requirement_set_id, actor):
        self.data["s"] = {"schedule_id":"s","name":name,"requirement_set_id":requirement_set_id,"enabled":False,"next_run_at":None}; return self.data["s"]
    def rename_schedule(self, sid, name, actor): self.data[sid]["name"] = name; return self.data[sid]
    def create_version(self, schedule_id, config, actor): self.version += 1; return {"schedule_version_id":f"v{self.version}","version_number":self.version,"status":"draft"}
    def approve_version(self, **kw): return {"status":"approved","version_number":kw["version_number"]}
    def set_enabled(self, **kw): self.data[kw["schedule_id"]]["enabled"] = kw["enabled"]; return self.data[kw["schedule_id"]]


def app(role=None):
    value=FastAPI(); value.include_router(router); service=ScheduleService(Store()); value.dependency_overrides[schedule_service]=lambda:service
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
