from fastapi.testclient import TestClient
from api.main import app
def test_lifespan_has_one_worker_and_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_JOBS_DB_PATH",str(tmp_path/"j.db")); monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT",str(tmp_path/"r"))
    with TestClient(app):
        worker=app.state.report_job_worker
        assert worker.thread.is_alive()
        worker.start(); assert worker.thread.is_alive()
    assert worker.stop_event.is_set()
