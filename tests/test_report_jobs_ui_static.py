"""Static and route contract for the real Report Job browser UI."""
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient

from api.main import app
from api.routers.editor import editor_static_asset, report_jobs_page


STATIC = Path(__file__).resolve().parents[1] / "sra_api" / "static"


def test_report_job_ui_route_and_allowlisted_assets():
    page = report_jobs_page()
    assert page.path == STATIC / "report_jobs.html"
    assert page.headers["Cache-Control"] == "no-store"
    assert page.headers["Referrer-Policy"] == "no-referrer"
    assert "nosniff" in page.headers["X-Content-Type-Options"]
    assert "default-src 'none'" in page.headers["Content-Security-Policy"]
    assert editor_static_asset("report_jobs_ui.js").media_type == "application/javascript"
    assert editor_static_asset("report_jobs_ui.css").media_type == "text/css"
    assert editor_static_asset("report_jobs_auth.js").media_type == "application/javascript"
    with TestClient(app) as client:
        assert client.get("/report-jobs").status_code == 200
        assert client.get("/static/report_jobs_ui.js").status_code == 200
        assert client.get("/static/report_jobs_auth.js").status_code == 200
        assert client.get("/", follow_redirects=False).headers.get("location") == "/editor"
        assert client.get("/static/report_jobs_ui.css").status_code == 200
        assert client.get("/static/report_jobs_ui.bad").status_code == 404


def test_report_job_ui_real_status_contract_and_no_token_persistence():
    html = (STATIC / "report_jobs.html").read_text(encoding="utf-8")
    js = (STATIC / "report_jobs_ui.js").read_text(encoding="utf-8")
    editor = (STATIC / "editor.html").read_text(encoding="utf-8")
    bootstrap = (STATIC / "editor_bootstrap.js").read_text(encoding="utf-8")
    assert 'id="authToken" type="password" hidden' in html
    assert 'id="reportAuthUsername"' in html
    assert 'id="reportAuthPassword" type="password"' in html
    assert 'id="reportLoginBtn"' in html
    assert 'id="reportLogoutBtn"' in html
    assert 'src="/static/report_jobs_auth.js"' in html
    shared_auth = (STATIC / "report_jobs_auth.js").read_text(encoding="utf-8")
    assert "'sra_editor_token'" in shared_auth
    assert "'/v1/auth/login'" in shared_auth
    assert "'/v1/auth/me'" in shared_auth
    assert "'/v1/auth/logout'" in shared_auth
    assert "credentials: 'omit'" in shared_auth
    assert "document.cookie" not in shared_auth
    assert "innerHTML" not in shared_auth
    assert 'src="/static/report_jobs_ui.js"' in html
    assert 'href="/static/report_jobs_ui.css"' in html
    assert 'id="srafEditorExternalNav"' in editor
    assert 'id="reportJobsBtn"' in (STATIC / "excel_global_nav.js").read_text(encoding="utf-8")
    assert "location.href = '/report-jobs'" in bootstrap
    assert "/v1/report/jobs/" in js
    assert "phase.elapsed" not in js  # respect existing progress.elapsed_seconds
    for phase in ("queued", "unobserved", "agent_execution", "docx_export",
                  "finalizing", "completed", "failed", "interrupted", "cancelled"):
        assert phase + ":" in js
    assert "credentials: 'omit'" in js
    assert "cache: 'no-store'" in js
    assert "textContent" in js
    assert 'id="jobStatusFilter"' in html
    assert '<option value="cancelled">已取消</option>' in html
    assert "'jobStatusFilter').addEventListener('change'" in js
    assert "&status=" in js
    assert 'id="listJobsBtn"' in html
    assert 'id="jobRows"' in html
    assert 'id="jobPrev"' in html and 'id="jobNext"' in html
    assert "/v1/report/jobs?limit=20&offset=" in js
    assert "method: 'GET'" in js
    assert "historyGeneration" in js
    assert "clearHistory();" in js
    assert "item.job_id" in js
    assert "taipeiCreatedTime(item.created_at)" in js
    assert "timeZone: 'Asia/Taipei'" in js
    assert 'class="global-tree-nav"' in html
    assert '/static/excel_global_nav.js?v=20261118-shared' in html
    assert 'id="retrySubmitBtn"' in html
    assert 'id="discardSubmitBtn"' in html
    assert "'Idempotency-Key': attempt.key" in js
    assert "window.crypto.randomUUID()" in js
    assert "pendingSubmission = attempt" in js
    assert "pendingSubmission = null" in js
    assert "await sendCreate(pendingSubmission)" in js
    assert "abortDownload();" in js
    assert "signal: ctrl.signal" in js
    assert "authVersion === version && completedId === id" in js
    assert "if (!stillAuthorized()) return;" in js
    for forbidden in ("localStorage.", "sessionStorage.", "innerHTML", "document.cookie",
                      "eval(", "window.prompt(", "location.search"):
        assert forbidden not in js


def test_report_job_browser_javascript_syntax_and_flow():
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js required for hosted UI behavior gate")
    script = STATIC / "report_jobs_ui.js"
    suite = Path(__file__).with_name("report_jobs_ui_flow.cjs")
    for cmd in (
        [node, "--check", str(script)],
        [node, "--check", str(STATIC / "report_jobs_auth.js")],
        [node, str(suite)],
        [node, str(Path(__file__).with_name("report_jobs_shared_auth.cjs"))],
    ):
        result = subprocess.run(cmd, cwd=STATIC.parents[1], capture_output=True,
                                text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr[-1600:]
