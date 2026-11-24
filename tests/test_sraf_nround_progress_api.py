"""Real auth + SQLite read-only route; never starts a provider."""
import sqlite3
from fastapi.testclient import TestClient
from api.main import app
from api.security.service_key_store import ServiceKeyStore
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore


def test_nround_progress_route_exact_owner_no_grant(tmp_path, monkeypatch):
    import api.security.service_key_store as key_module
    keys = ServiceKeyStore(tmp_path / "keys.json")
    monkeypatch.setattr(key_module, "SERVICE_KEY_STORE", keys)
    monkeypatch.setenv("REPORT_JOBS_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT", str(tmp_path / "reports"))
    def auth(name, scopes):
        _, raw = keys.create(name, scopes, "pytest")
        return {"Authorization": "Bearer " + raw}
    owner = auth("owner", ["report:job:create", "report:job:read"])
    other = auth("other", ["report:job:read", "report:job:admin"])
    write_only = auth("write-only", ["report:job:create"])
    with TestClient(app) as client:
        app.state.report_job_worker.stop()
        store = app.state.report_job_store
        job = client.post("/v1/report/jobs", headers=owner, json={"prompt":"PRIVATE_PROMPT"}).json()["job_id"]
        url = f"/v1/report/jobs/{job}/nround-progress"
        status_url = f"/v1/report/jobs/{job}"
        assert client.get(status_url, headers=owner).json()["nround_progress_available"] is False
        assert client.get(url, headers=owner).status_code == 404
        with sqlite3.connect(store.db_path) as con:
            assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sraf_nround_checkpoints'").fetchone()[0] == 0
        sidecar = NroundCheckpointStore(store.db_path)
        sidecar.initialize()
        assert sidecar.create(job)
        owner_status = client.get(status_url, headers=owner)
        assert owner_status.status_code == 200
        assert owner_status.json()["nround_progress_available"] is True
        admin_status = client.get(status_url, headers=other)
        assert admin_status.status_code == 200
        assert admin_status.json()["nround_progress_available"] is False
        assert client.get(url).status_code == 401
        assert client.get(url, headers=write_only).status_code == 403
        assert client.get(url, headers=other).status_code == 404
        result = client.get(url, headers=owner)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        body = result.json()
        assert body["report_job_status"] == "queued" and body["state"] == "QUEUED"
        assert body["completed_rounds"] == 0 and body["word_download_authorized"] is False
        assert "PRIVATE_PROMPT" not in result.text and "lease_hash" not in body
        assert store.get(job).status == "queued"
        with sqlite3.connect(store.db_path) as con:
            con.execute("ALTER TABLE sraf_nround_checkpoints ADD COLUMN PRIVATE_FIELD TEXT")
        assert client.get(status_url, headers=owner).json()["nround_progress_available"] is False
        response = client.get(url, headers=owner)
        assert response.status_code == 503 and "PRIVATE" not in response.text
