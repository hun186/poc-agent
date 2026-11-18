"""Regression: 9002 cross-page navigation has one source, not copied HTML."""
from pathlib import Path
import shutil
import subprocess

STATIC = Path(__file__).resolve().parents[1] / "sra_api" / "static"
SHARED_PAGES = (
    "agent_data_flow.html",
    "excel_to_sql_dashboard.html",
    "excel_to_sql_import_center.html",
    "excel_to_sql_task_configs.html",
    "excel_to_sql_source_editor.html",
    "excel_to_sql_source_dashboard.html",
    "report_jobs.html",
    "requirement_product_explorer.html",
)


def test_legacy_and_report_pages_use_shared_menu_source():
    source = (STATIC / "excel_global_nav.js").read_text(encoding="utf-8")
    for label, route in (
        ("報告任務進度", "/report-jobs"),
        ("需求任務與執行紀錄", "/requirement-product"),
        ("代理人資料流程圖", "/agent-data-flow"),
    ):
        assert label in source and route in source
    for filename in SHARED_PAGES:
        html = (STATIC / filename).read_text(encoding="utf-8")
        assert "global-tree-nav" in html, filename
        assert "/static/excel_global_nav.js?v=20261118-shared" in html, filename
        assert "<details><summary>ES 資料庫</summary>" not in html, filename
        assert "onclick=\"location.href=" not in html, filename
    editor = (STATIC / "editor.html").read_text(encoding="utf-8")
    assert 'id="srafEditorExternalNav"' in editor
    assert 'id="reportJobsBtn"' not in editor
    assert editor.index("/static/excel_global_nav.js") < editor.index("/static/editor_bootstrap.js")
    assert 'aria-current' in source
    assert 'createElement' in source
    assert 'innerHTML' not in source


def test_shared_navigation_browser_regression():
    node = shutil.which("node")
    assert node, "Node.js required by hosted UI regression gate"
    for cmd in (
        [node, "--check", str(STATIC / "excel_global_nav.js")],
        [node, str(Path(__file__).with_name("sraf_shared_nav_flow.cjs"))],
    ):
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        assert run.returncode == 0, run.stderr[-1500:]
