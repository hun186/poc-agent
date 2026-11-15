"""Authenticated browser-link contract for accepted, queued Report Jobs.

Synthetic local SQLite/API calls only: no ES, LLM or document generation.
"""
from fastapi.testclient import TestClient

from api.main import app
from api.security.service_key_store import ServiceKeyStore
from sra_api.routers.report_jobs import _browser_status_url


def test_browser_fragment_url_is_only_for_safe_opaque_job_ids():
    assert _browser_status_url("rpt_A-42") == "/report-jobs#job=rpt_A-42"
    for invalid in ("", "../other", "a?token=b", "id#extra", "中文", "x" * 129, None):
        assert _browser_status_url(invalid) is None


def test_accepted_job_has_no_secret_browser_link_and_remains_owner_scoped(
    tmp_path, monkeypatch,
):
    import api.security.service_key_store as key_module

    monkeypatch.setenv("REPORT_JOBS_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT", str(tmp_path / "reports"))
    keys = ServiceKeyStore(tmp_path / "keys.json")
    monkeypatch.setattr(key_module, "SERVICE_KEY_STORE", keys)
    _, first_key = keys.create(
        "creator", ["report:job:create", "report:job:read", "report:job:download"], "pytest"
    )
    _, other_key = keys.create("other", ["report:job:read"], "pytest")
    headers = {"Authorization": f"Bearer {first_key}"}
    other = {"Authorization": f"Bearer {other_key}"}

    with TestClient(app) as client:
        app.state.report_job_worker.stop()
        accepted = client.post("/v1/report/jobs", json={"prompt": "test report"}, headers=headers)
        assert accepted.status_code == 202
        data = accepted.json()
        job_id = data["job_id"]
        fragment = f"/report-jobs#job={job_id}"
        assert data["browser_status_url"] == fragment
        assert data["status"] == "queued"
        assert first_key not in accepted.text
        assert "Bearer " not in accepted.text
        assert "test report" not in accepted.text
        # A fragment is a UI prefill, never an unprotected status endpoint.
        assert client.get(f"/v1/report/jobs/{job_id}").status_code == 401
        assert client.get(f"/v1/report/jobs/{job_id}", headers=other).status_code == 404
        status = client.get(f"/v1/report/jobs/{job_id}", headers=headers)
        assert status.status_code == 200
        assert status.json()["browser_status_url"] == fragment
        assert first_key not in status.text
        assert "test report" not in status.text
        assert client.get(f"/v1/report/jobs/{job_id}/word", headers=headers).status_code == 409
