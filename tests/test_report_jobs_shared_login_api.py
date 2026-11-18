"""Real SRAF user login -> owner-scoped Report Job API, no worker or external IO."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import editor_auth, report_jobs
import api.services.auth_store as auth_store_module
from api.services.report_job_store import ReportJobStore


def test_existing_sraf_login_can_access_only_own_report_jobs(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    bootstrap = tmp_path / "bootstrap.json"
    bootstrap.write_text(json.dumps({"superusers": [
        {"username": "report_owner", "password": "TestOwnerPassword!2026"},
        {"username": "different_owner", "password": "TestOtherPassword!2026"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("SRA_AUTH_USERS_FILE", str(users))
    monkeypatch.setenv("SRA_BOOTSTRAP_SUPERUSERS_FILE", str(bootstrap))
    monkeypatch.setenv("SRA_AUTH_SECRET", "sraf-private-test-key-" + "z" * 48)
    monkeypatch.setenv("SRA_EDITOR_LOGIN_AUDIT_FILE", str(tmp_path / "audit.json"))
    monkeypatch.setenv("SRA_EDITOR_AUDIT_LOG", str(tmp_path / "events.jsonl"))
    store = auth_store_module.AuthStore()
    monkeypatch.setattr(auth_store_module, "AUTH_STORE", store)

    app = FastAPI()
    app.include_router(editor_auth.router)
    app.include_router(report_jobs.router)
    report_store = ReportJobStore(tmp_path / "private-jobs.sqlite3")
    report_store.initialize()
    app.state.report_job_store = report_store

    with TestClient(app) as client:
        assert client.get("/v1/report/jobs").status_code == 401
        owner = client.post("/v1/auth/login", json={
            "username": "report_owner", "password": "TestOwnerPassword!2026"
        })
        assert owner.status_code == 200
        owner_headers = {"Authorization": "Bearer " + owner.json()["access_token"]}
        assert client.get("/v1/auth/me", headers=owner_headers).status_code == 200
        created = client.post("/v1/report/jobs", json={"prompt": "PRIVATE_REPORT"},
                              headers={**owner_headers, "Idempotency-Key": "private-report-1"})
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        mine = client.get("/v1/report/jobs", headers=owner_headers)
        assert mine.status_code == 200
        assert [x["job_id"] for x in mine.json()["items"]] == [job_id]

        other = client.post("/v1/auth/login", json={
            "username": "different_owner", "password": "TestOtherPassword!2026"
        })
        assert other.status_code == 200
        other_headers = {"Authorization": "Bearer " + other.json()["access_token"]}
        assert client.get("/v1/report/jobs", headers=other_headers).json()["items"] == []
        assert client.get("/v1/report/jobs/" + job_id, headers=other_headers).status_code == 404

        assert client.post("/v1/auth/logout", headers=owner_headers).status_code == 200
        assert client.get("/v1/report/jobs", headers=owner_headers).status_code == 401
        assert client.get("/v1/report/jobs", headers=other_headers).status_code == 200
