from fastapi.testclient import TestClient
from api.main import app
from tests.security_test_utils import bearer

def test_create_status_idempotency_and_download_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_JOBS_DB_PATH",str(tmp_path/"j.db")); monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT",str(tmp_path/"r"))
    auth=bearer(monkeypatch,tmp_path,["report:job:create","report:job:read","report:job:download"])
    with TestClient(app) as client:
        body={"prompt":" report ","filename":"../../x.docx","session_id":"s"}
        first=client.post("/v1/report/jobs",json=body,headers={**auth,"Idempotency-Key":"k"})
        second=client.post("/v1/report/jobs",json=body,headers={**auth,"Idempotency-Key":"k"})
        assert first.status_code==202 and second.json()["job_id"]==first.json()["job_id"]
        job_id=first.json()["job_id"]
        assert client.get(f"/v1/report/jobs/{job_id}",headers=auth).status_code==200
        assert client.get(f"/v1/report/jobs/{job_id}/word",headers=auth).status_code in (409,500)
        assert client.post("/v1/report/jobs",json={"prompt":"different"},headers={**auth,"Idempotency-Key":"k"}).status_code==409
        assert client.get("/v1/report/jobs/nope",headers=auth).status_code==404
def test_openapi_and_cors(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_JOBS_DB_PATH",str(tmp_path/"j.db")); monkeypatch.setenv("CORS_ALLOWED_ORIGINS","https://example.test")
    with TestClient(app) as client:
        spec=client.get("/openapi.json").json(); assert "/v1/report/jobs" in spec["paths"]
        response=client.options("/v1/report/jobs",headers={"Origin":"https://example.test","Access-Control-Request-Method":"POST","Access-Control-Request-Headers":"Idempotency-Key,Content-Type"})
        assert response.status_code==200 and "idempotency-key" in response.headers["access-control-allow-headers"].lower()


def test_report_job_history_is_owner_only_even_for_admin(tmp_path, monkeypatch):
    from api.security.service_key_store import ServiceKeyStore
    import api.security.service_key_store as key_store_module

    monkeypatch.setenv("REPORT_JOBS_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT", str(tmp_path / "reports"))
    store = ServiceKeyStore(tmp_path / "service-keys.json")
    monkeypatch.setattr(key_store_module, "SERVICE_KEY_STORE", store)
    scopes = ["report:job:create", "report:job:read"]
    _, raw_a = store.create("client-a", scopes, "pytest")
    _, raw_b = store.create("client-b", scopes, "pytest")
    _, raw_admin = store.create("auditor", ["report:job:read", "report:job:admin"], "pytest")
    auth_a = {"Authorization": f"Bearer {raw_a}"}
    auth_b = {"Authorization": f"Bearer {raw_b}"}
    auth_admin = {"Authorization": f"Bearer {raw_admin}"}

    with TestClient(app) as client:
        assert client.get("/v1/report/jobs").status_code == 401
        assert client.get("/v1/report/jobs?limit=0", headers=auth_a).status_code == 422
        assert client.get("/v1/report/jobs?limit=101", headers=auth_a).status_code == 422
        assert client.get("/v1/report/jobs?offset=10001", headers=auth_a).status_code == 422
        first = client.post("/v1/report/jobs", json={"prompt": "VERY PRIVATE A1"},
                            headers={**auth_a, "Idempotency-Key": "a-1"})
        second = client.post("/v1/report/jobs", json={"prompt": "VERY PRIVATE A2"},
                             headers={**auth_a, "Idempotency-Key": "a-2"})
        different = client.post("/v1/report/jobs", json={"prompt": "VERY PRIVATE B1"},
                                headers={**auth_b, "Idempotency-Key": "b-1"})
        assert first.status_code == second.status_code == different.status_code == 202
        own = client.get("/v1/report/jobs?limit=100&offset=0", headers=auth_a)
        assert own.status_code == 200
        rows = own.json()
        assert rows["limit"] == 100 and rows["offset"] == 0
        assert {x["job_id"] for x in rows["items"]} == {
            first.json()["job_id"], second.json()["job_id"]
        }
        assert "VERY PRIVATE" not in own.text
        for item in rows["items"]:
            assert set(item) == {
                "job_id", "status", "filename", "created_at", "started_at",
                "finished_at", "phase", "phase_updated_at", "failure_category",
            }
            for forbidden in ("prompt", "metadata", "request_hash",
                              "idempotency_key", "owner_id", "owner_kind",
                              "session_id", "error_message"):
                assert forbidden not in item
        b_list = client.get("/v1/report/jobs", headers=auth_b)
        assert [item["job_id"] for item in b_list.json()["items"]] == [different.json()["job_id"]]
        admin = client.get("/v1/report/jobs", headers=auth_admin)
        assert admin.status_code == 200 and admin.json()["items"] == []
        one = client.get("/v1/report/jobs?limit=1&offset=1", headers=auth_a)
        assert len(one.json()["items"]) == 1
        assert one.json()["items"][0]["job_id"] in {
            first.json()["job_id"], second.json()["job_id"]
        }

def test_report_job_history_status_filter_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_JOBS_DB_PATH", str(tmp_path / "filtered.db"))
    monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT", str(tmp_path / "reports"))
    auth = bearer(monkeypatch, tmp_path, ["report:job:create", "report:job:read"])
    with TestClient(app) as client:
        assert client.get("/v1/report/jobs?status=unknown", headers=auth).status_code == 422
        assert client.get("/v1/report/jobs?status=running%27%20OR%201%3D1",
                          headers=auth).status_code == 422
        job = client.post("/v1/report/jobs", json={"prompt": "PRIVATE_STATUS_TEST"},
                          headers={**auth, "Idempotency-Key": "status-test"})
        assert job.status_code == 202
        for status in ("queued", "running", "completed", "failed", "interrupted"):
            response = client.get("/v1/report/jobs?limit=10&offset=0&status=" + status,
                                  headers=auth)
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == status
            assert payload["limit"] == 10
            assert all(item["status"] == status for item in payload["items"])
            assert "PRIVATE_STATUS_TEST" not in response.text
        assert client.get("/v1/report/jobs", headers=auth).json()["status"] is None
