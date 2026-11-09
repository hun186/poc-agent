"""Read-only Requirement Product browser contract; no live database required."""
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient

from api.main import app
from api.routers.editor import editor_static_asset, requirement_product_explorer_page

STATIC = Path(__file__).resolve().parents[1] / "sra_api" / "static"


def test_product_readonly_explorer_route_and_static_allowlist():
    response = requirement_product_explorer_page()
    assert response.path == STATIC / "requirement_product_explorer.html"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert editor_static_asset("requirement_product_explorer.js").media_type == "application/javascript"
    assert editor_static_asset("requirement_product_explorer.css").media_type == "text/css"
    with TestClient(app) as client:
        assert client.get("/requirement-product").status_code == 200
        assert client.get("/static/requirement_product_explorer.js").status_code == 200
        assert client.get("/static/requirement_product_explorer.css").status_code == 200
        assert client.get("/static/requirement_product_explorer.executable").status_code == 404


def test_product_explorer_is_readonly_and_does_not_store_tokens():
    html = (STATIC / "requirement_product_explorer.html").read_text(encoding="utf-8")
    js = (STATIC / "requirement_product_explorer.js").read_text(encoding="utf-8")
    editor = (STATIC / "editor.html").read_text(encoding="utf-8")
    bootstrap = (STATIC / "editor_bootstrap.js").read_text(encoding="utf-8")
    assert 'id="authToken" type="password"' in html
    assert 'src="/static/requirement_product_explorer.js"' in html
    assert 'id="requirementProductBtn"' in editor
    assert "location.href = '/requirement-product'" in bootstrap
    for path in (
        "/v1/requirement-tasks?",
        "/v1/requirement-tasks/",
        "/v1/requirement-runs/",
    ):
        assert path in js
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "innerHTML", "eval(", "location.search"):
        assert forbidden not in js
    assert "method: 'GET'" in js
    assert "credentials: 'omit'" in js
    assert "redirect: 'error'" in js
    assert 'id="taskDetailBtn"' in html
    assert 'id="runDetailBtn"' in html
    assert 'id="taskDetails"' in html
    assert 'id="runDetails"' in html
    assert 'id="loadAllRuns"' in html
    assert 'id="allRunRows"' in html
    assert 'id="allRunPrev"' in html and 'id="allRunNext"' in html
    assert 'id="openRunTaskBtn"' in html
    assert "/v1/requirement-runs?limit=" in js
    assert "openAllRun(run.run_id, run.task_id)" in js
    assert "runs.length > LIMIT" in js
    assert "loadTaskDetail()" in js and "loadRunDetail()" in js
    assert "item.task_id !== id" in js
    assert "item.run_id !== id || item.task_id !== state.taskId" in js


def test_product_explorer_browser_flow():
    node = shutil.which("node")
    assert node is not None, "Node.js required for hosted Product browser behavior gate"
    script = STATIC / "requirement_product_explorer.js"
    suite = Path(__file__).with_name("requirement_product_explorer_flow.cjs")
    for args in ([node, "--check", str(script)], [node, str(suite)]):
        result = subprocess.run(args, cwd=STATIC.parents[1],
                                capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr[-2000:]



def test_product_preview_ui_is_opt_in_bounded_and_no_persistence():
    html = (STATIC / "requirement_product_explorer.html").read_text(encoding="utf-8")
    js = (STATIC / "requirement_product_preview.js").read_text(encoding="utf-8")
    assert 'src="/static/requirement_product_preview.js"' in html
    assert 'id="previewProfile"' in html
    assert 'id="previewMode"' in html
    assert 'id="previewFile"' in html
    assert 'id="previewJson"' in html
    assert 'id="previewBtn"' in html
    assert 'id="loadProfilesBtn"' in html
    assert 'id="previewProfileSelect"' in html
    assert "/v1/requirement-import-profiles" in js
    assert "clearProfileOptions()" in js
    assert "profile.active_version_id" in js
    assert editor_static_asset("requirement_product_preview.js").media_type == "application/javascript"
    assert "MAX_FILE = 10 * 1024 * 1024" in js
    assert "MAX_JSON = 1024 * 1024" in js
    assert "POST" in js and "/v1/requirement-task-previews" in js
    assert "append('task'" in js
    assert "append('requirements_json'" in js
    assert "append('file'" in js
    assert "credentials: 'omit'" in js
    assert "redirect: 'error'" in js
    assert "textContent" in js
    assert "controller.abort()" in js
    assert "window.addEventListener('pagehide'" in js
    for forbidden in ("innerHTML", "localStorage", "sessionStorage", "document.cookie",
                      "location.search", "eval(", "new Function("):
        assert forbidden not in js
    with TestClient(app) as client:
        assert client.get("/static/requirement_product_preview.js").status_code == 200


def test_product_preview_simulated_browser_flow():
    node = shutil.which("node")
    assert node is not None, "Node.js required for browser test"
    script = STATIC / "requirement_product_preview.js"
    suite = Path(__file__).with_name("requirement_product_preview_flow.cjs")
    for args in ([node, "--check", str(script)], [node, str(suite)]):
        proc = subprocess.run(args, cwd=STATIC.parents[1], capture_output=True,
                              text=True, timeout=20, check=False)
        assert proc.returncode == 0, proc.stderr[-2500:]
