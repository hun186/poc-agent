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
    with TestClient(app) as client:
        assert client.get("/report-jobs").status_code == 200
        assert client.get("/static/report_jobs_ui.js").status_code == 200
        assert client.get("/static/report_jobs_ui.css").status_code == 200
        assert client.get("/static/report_jobs_ui.bad").status_code == 404


def test_report_job_ui_real_status_contract_and_no_token_persistence():
    html = (STATIC / "report_jobs.html").read_text(encoding="utf-8")
    js = (STATIC / "report_jobs_ui.js").read_text(encoding="utf-8")
    editor = (STATIC / "editor.html").read_text(encoding="utf-8")
    bootstrap = (STATIC / "editor_bootstrap.js").read_text(encoding="utf-8")
    assert 'id="authToken" type="password"' in html
    assert 'src="/static/report_jobs_ui.js"' in html
    assert 'href="/static/report_jobs_ui.css"' in html
    assert 'id="reportJobsBtn"' in editor
    assert "location.href = '/report-jobs'" in bootstrap
    assert "/v1/report/jobs/" in js
    assert "phase.elapsed" not in js  # respect existing progress.elapsed_seconds
    for phase in ("queued", "unobserved", "agent_execution", "docx_export",
                  "finalizing", "completed", "failed", "interrupted"):
        assert phase + ":" in js
    assert "credentials: 'omit'" in js
    assert "cache: 'no-store'" in js
    assert "textContent" in js
    for forbidden in ("localStorage.", "sessionStorage.", "innerHTML", "document.cookie",
                      "eval(", "window.prompt(", "location.search"):
        assert forbidden not in js


def test_report_job_browser_javascript_syntax_and_flow():
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js required for hosted UI behavior gate")
    script = STATIC / "report_jobs_ui.js"
    suite = Path(__file__).with_name("report_jobs_ui_flow.cjs")
    for cmd in ([node, "--check", str(script)], [node, str(suite)]):
        result = subprocess.run(cmd, cwd=STATIC.parents[1], capture_output=True,
                                text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr[-1600:]
