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
