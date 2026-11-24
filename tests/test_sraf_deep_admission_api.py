"""Real JWT + SQLite HTTP admission/read ownership, synthetic artifact only."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from docx import Document

import api.security.service_key_store as keys_module
from api.services.auth_support import AuthUser
from api.services.auth_tokens import create_token
from api.security.scopes import REGISTERED_SCOPES
from api.routers import report_jobs, nround_progress, nround_admission
from api.services.report_job_worker import ReportJobWorker
from api.services.sraf_adaptive_job_runtime import AdaptiveJobRuntime, create_adaptive_job
from api.services.sraf_deep_scope_policy import compile_explicit_deep_question
from test_sraf_deep_scope_policy import setup, QUESTION


def test_deep_submit_owner_fence_and_account_recreation(tmp_path, monkeypatch):
    auth, store, policy, _, _ = setup(tmp_path, monkeypatch)
    auth.approve_user("other", "superuser", approved_by="operator")
    def user_header(name):
        row = auth.get_user(name)
        return {"Authorization": "Bearer " + create_token(
            AuthUser(name, row["role"], "active"), auth.get_user)}
    owner = user_header("owner")
    other = user_header("other")
    keys = keys_module.ServiceKeyStore(tmp_path / "service.json")
    monkeypatch.setattr(keys_module, "SERVICE_KEY_STORE", keys)
    _, raw = keys.create("owner", sorted(REGISTERED_SCOPES), "pytest")
    service = {"Authorization": "Bearer " + raw}
    app = FastAPI()
    app.include_router(report_jobs.router)
    app.include_router(nround_progress.router)
    app.include_router(nround_admission.router)
    app.state.report_job_store = store
    reports = tmp_path / "reports"
    reports.mkdir()
    app.state.report_jobs_reports_root = reports
    def forbidden(*_, **__):
        raise AssertionError("test must not start providers")
    runtime = AdaptiveJobRuntime(forbidden, forbidden, forbidden,
                                 policy.check_owner_index, policy.check_question_branches, forbidden)
    worker = ReportJobWorker(store, reports, adaptive_runtime=runtime)
    app.state.report_job_worker = worker
    body = {"prompt": QUESTION, "filename": "private-report.docx"}
    url = "/v1/report/jobs/deep"
    with TestClient(app) as c:
        assert c.post(url, json=body).status_code == 401
        assert c.post(url, headers=owner, json=body).status_code == 400
        head = {**owner, "Idempotency-Key": "deep-one"}
        assert c.post(url, headers=head, json=body).status_code == 503
        app.state.deep_scope_policy = policy
        assert c.post(url, headers={**service, "Idempotency-Key": "a"}, json=body).status_code == 403
        assert c.post(url, headers={**other, "Idempotency-Key": "a"}, json=body).status_code == 403
        assert c.post(url, headers=head, json={**body, "owner_id": "other"}).status_code == 422
        assert c.post(url, headers=head, json={"prompt": "任意未驗證問題"}).status_code == 422
        accepted = c.post(url, headers=head, json=body)
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        assert accepted.json()["status"] == "queued"
        assert accepted.json()["browser_status_url"] == "/report-jobs#job=" + job_id
        assert "news_test" not in accepted.text and "adaptive_owner_binding" not in accepted.text
        assert c.post(url, headers=head, json=body).json()["job_id"] == job_id
        assert c.post(url, headers=head, json={**body, "filename": "other.docx"}).status_code == 409
        status = "/v1/report/jobs/" + job_id
        owner_view = c.get(status, headers=owner)
        assert owner_view.status_code == 200
        assert owner_view.json()["nround_progress_available"] is True
        assert owner_view.json()["metadata"] == {} and owner_view.json()["options"] == {}
        assert c.get(status + "/nround-progress", headers=owner).status_code == 200
        assert c.get(status + "/word", headers=owner).status_code == 409
        assert c.get("/v1/report/jobs", headers=owner).json()["items"][0]["job_id"] == job_id
        for foreign in (other, service):
            assert c.get(status, headers=foreign).status_code == 404
            assert c.get(status + "/nround-progress", headers=foreign).status_code == 404
            assert c.get(status + "/word", headers=foreign).status_code == 404
            assert c.post(status + "/cancel", headers=foreign).status_code == 404
        # Synthetic completed-artifact fixture for the existing download route.
        assert store.claim_next().job_id == job_id
        basename = job_id + ".docx"
        doc = Document()
        doc.add_paragraph("PRIVATE FIXTURE")
        doc.save(reports / basename)
        store.complete(job_id, "fixture", basename)
        download = c.get(status + "/word", headers=owner)
        assert download.status_code == 200 and download.headers["cache-control"] == "no-store"
        assert c.get(status + "/word", headers=other).status_code == 404
        ordinary = c.post("/v1/report/jobs", headers=owner, json={"prompt": "ordinary"})
        ordinary_id = ordinary.json()["job_id"]
        unbound, _ = create_adaptive_job(store, intent=compile_explicit_deep_question(QUESTION, ("news_test",)),
                                        owner_id="owner", idempotency_key="unbound", max_active_jobs=100)
        assert c.get("/v1/report/jobs/" + unbound.job_id, headers=owner).status_code == 404
        ids = {i["job_id"] for i in c.get("/v1/report/jobs", headers=owner).json()["items"]}
        assert ids == {job_id, ordinary_id}
        # The same username is a NEW account, not the old deep Job owner.
        auth.delete_user("owner")
        auth.register("owner", "SyntheticReplacementPassword!2026")
        auth.approve_user("owner", "superuser", approved_by="operator")
        replacement = user_header("owner")
        for suffix in ("", "/nround-progress", "/word"):
            assert c.get(status + suffix, headers=replacement).status_code == 404
        assert c.post(status + "/cancel", headers=replacement).status_code == 404
        ids = {i["job_id"] for i in c.get("/v1/report/jobs?limit=1&offset=0", headers=replacement).json()["items"]}
        assert ids == {ordinary_id}
        assert c.post(url, headers={**replacement, "Idempotency-Key": "new"}, json=body).status_code == 403


def test_real_application_exposes_explicit_deep_admission_route():
    from api.main import app
    # Exercise the real routing stack rather than inspect FastAPI include-router internals.
    # Without authentication the registered POST must reject before admission.
    response = TestClient(app).post("/v1/report/jobs/deep", json={"prompt": QUESTION})
    assert response.status_code == 401
