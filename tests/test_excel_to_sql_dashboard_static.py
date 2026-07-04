import re
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app

STATIC_ROOT = Path(__file__).resolve().parents[1] / "sra_api" / "static"
DASHBOARD_HTML = STATIC_ROOT / "excel_to_sql_dashboard.html"
DASHBOARD_JS = STATIC_ROOT / "excel_to_sql_dashboard_app.js"


def test_excel_pages_static_scripts_are_served_by_static_route():
    html_files = [
        "excel_to_sql_dashboard.html",
        "excel_to_sql_import_center.html",
        "excel_to_sql_task_configs.html",
        "excel_to_sql_source_editor.html",
        "excel_to_sql_source_dashboard.html",
        "agent_data_flow.html",
    ]
    script_urls = set()
    for filename in html_files:
        html = (STATIC_ROOT / filename).read_text(encoding="utf-8")
        script_urls.update(re.findall(r'<script src="([^"]+)"', html))

    assert "/static/excel_to_sql_source_editor_app.js?v=sort-20260703-audit-metadata" in script_urls
    assert "/static/excel_to_sql_source_dashboard_app.js?v=20260703-source-dashboard-group-grid" in script_urls
    for script_url in sorted(script_urls):
        response = TestClient(app).get(script_url)

        assert response.status_code == 200, script_url
        assert "application/javascript" in response.headers.get("content-type", ""), script_url


def test_sql_source_editor_sort_controls_reset_for_task_specific_columns_and_use_compact_help():
    html = (STATIC_ROOT / "excel_to_sql_source_editor.html").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "excel_to_sql_source_editor_app.js").read_text(encoding="utf-8")
    tools = (STATIC_ROOT / "audit_tools.js").read_text(encoding="utf-8")

    assert "$('config').value.trim() === state.loadedConfig" in js
    assert "state.loadedConfig = $('config').value.trim()" in js
    assert "filter((spec) => allowed.has(spec.field))" in tools
    assert "sql-sort-rank" in tools
    assert "sql-sort-help" in tools
    assert "可新增多個排序欄位；依上到下優先排序。排序與篩選會送到 SQL Server 後再分頁。" in html
    assert '<span class="muted">依上到下優先排序；排序與篩選會送到 SQL Server 後再分頁。</span>' not in tools


def test_dashboard_audit_sort_controls_start_on_new_grid_row():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert '.full-row { grid-column: 1 / -1; }' in html
    assert '<div class="full-row"><label>複式排序</label><div id="recentSortControls" class="sql-sort-controls"></div></div>' in html


def test_sql_source_dashboard_group_checkboxes_use_responsive_grid():
    html = (STATIC_ROOT / "excel_to_sql_source_dashboard.html").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "excel_to_sql_source_dashboard_app.js").read_text(encoding="utf-8")

    assert 'grid-template-columns:repeat(auto-fit,minmax(180px,1fr))' in html
    assert '<span>${escapeHtml(name)}</span>' in js
    assert 'title="${escapeHtml(name)}"' in js


def dashboard_source() -> str:
    return (
        DASHBOARD_HTML.read_text(encoding="utf-8")
        + "\n"
        + DASHBOARD_JS.read_text(encoding="utf-8")
    )


def test_chart_bucket_selector_is_visible_in_chart_card_and_sent_to_api():
    html = dashboard_source()

    assert '<label for="chartBucket">曲線圖時間區間</label>' in html
    assert html.count('id="chartBucket"') == 1
    assert 'aria-label="曲線圖時間區間設定"' in html
    assert "chart_bucket: $('chartBucket').value" in html
    assert "$('chartBucket').addEventListener('change', applyAuditFilters)" in html
    assert '<script src="/static/audit_tools.js"></script>' in html
    assert "SraAuditTools.renderTimeSeriesChart" in html




def test_sql_source_dashboard_import_time_series_uses_shared_chart_helper():
    html = (STATIC_ROOT / "excel_to_sql_source_dashboard.html").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "excel_to_sql_source_dashboard_app.js").read_text(encoding="utf-8")

    assert '<script src="/static/audit_tools.js"></script>' in html
    assert 'id="importSeriesChart"' in html
    assert 'id="chartBucket"' in html
    assert "params.set('chart_bucket',$('chartBucket').value)" in js
    assert "SraAuditTools.renderTimeSeriesChart" in js
    assert "import_time_series" in js

def test_dashboard_refresh_and_audit_filters_preserve_explicit_time_range():
    html = dashboard_source()

    assert 'id="endTs" type="datetime-local" step="1"' in html
    assert "function fillRecentWindow()" in html
    assert "function resetDefaultWindow()" in html
    assert "使用回看天數" not in html
    assert '<div><label>載入列數上限</label><input id="limit" type="number" min="1" max="400000" value="50000" /></div>' in html
    assert "const pageSize = Math.max(1, Math.min(Number($('limit').value || state.recentPageSize || 50000), 400000));" in html
    assert "maxPageSize: 400000" in html
    assert "$('limit').addEventListener('change', applyAuditFilters)" in html
    assert '<button onclick="refreshDashboardNow()">重新整理</button>' in html
    assert (
        "function applyAuditFilters() { resetRecentPage(); loadDashboard(); }" in html
    )
    assert "function refreshDashboardNow() { loadDashboard(); }" in html
    assert "回看天數（起迄皆空時才生效）" in html
    assert "前往 Excel 匯入作業中心" not in html
    assert 'id="auditStartTs" type="datetime-local" step="1"' in html
    assert 'id="auditEndTs" type="datetime-local" step="1"' in html
    assert "function auditRangeStartIso()" in html
    assert "function auditRangeEndIso()" in html
    assert "Excel→SQL 匯入查詢儀表板" in html
    assert "匯入任務" in html
    assert "監控任務" not in html


def test_recent_audit_filters_include_destination_table():
    html = dashboard_source()

    assert (
        '<div class="field-label-row"><label for="destinationTableSummary">目的地 table</label><span class="help-tip"'
        in html
    )
    assert "點選多個項目後，點選選單外側會自動套用並收合。" in html
    assert '<details id="destinationTableDropdown" class="multi-select">' in html
    assert "function updateDestinationTableSummary()" in html
    assert "function applyDestinationTablePendingFilters()" in html
    assert "function closeDestinationTableDropdown(applyPending = false)" in html
    assert (
        "state.destinationTableDirty = true; updateDestinationTableSummary();" in html
    )
    assert (
        "destinationDropdown.addEventListener('toggle', () => { if (!destinationDropdown.open) applyDestinationTablePendingFilters(); });"
        in html
    )
    assert "destinationDropdown.addEventListener('focusout'" in html
    assert "closeDestinationTableDropdown(true)" in html
    assert "selectedValues('destinationTableFilter').forEach" in html
    assert "params.append('destination_table_filter', value)" in html
    assert "function renderDestinationTableOptions(options)" in html
    assert "renderDestinationTableOptions(data.destination_table_options || [])" in html
    assert "'destinationTableFilter'" in html


def test_recent_audit_filters_include_shared_username_picker():
    html = dashboard_source()

    assert '<label for="usernameSummary">使用者</label>' in html
    assert '<details id="usernameDropdown" class="multi-select">' in html
    assert "SraAuditTools.renderMultiFilterOptions" in html
    assert "SraAuditTools.summarizeMultiFilterSelection" in html
    assert "SraAuditTools.setVisibleMultiFilterSelection" in html
    assert "params.append('username_filter', value)" in html
    assert "state.usernameOptions = SraAuditTools.uniqueSortedValues" in html
    assert "renderUsernameFilter()" in html
    assert "closeUsernameDropdown(true)" in html
    assert '<th class="user-col">使用者</th>' in html
    assert '<td class="user-col">${escapeHtml(r.username || \'\')}</td>' in html


def test_recent_audit_table_gives_payload_more_width_than_file_column():
    html = dashboard_source()

    assert "main { padding:24px; max-width:none; margin:0 auto; }" in html
    assert "#recent { table-layout:fixed; width:100%; min-width:1700px; }" in html
    assert "#recent th, #recent td { box-sizing:border-box; overflow-wrap:anywhere; }" in html
    assert "#recent th.time-col, #recent td.time-col { width:10%; min-width:128px; }" in html
    assert "#recent th.status-col, #recent td.status-col { width:5%; }" in html
    assert "#recent th.file-col, #recent td.file-col { width:12%; max-width:260px; white-space:normal; word-break:normal; overflow-wrap:anywhere; }" in html
    assert "#recent th.user-col, #recent td.user-col { width:6%; }" in html
    assert "#recent th.select-col, #recent td.select-col { width:3%; text-align:center; }" in html
    assert "#recent th.op-col, #recent td.op-col { width:5%; max-width:130px; overflow-wrap:anywhere; }" in html
    assert "#recent th.action-col, #recent td.action-col { width:7%; }" in html
    assert "#recent th.payload-col, #recent td.payload-col { width:36%; min-width:560px; }" in html
    assert '<colgroup><col class="select-col"><col class="time-col"><col class="status-col"><col class="file-col"><col class="user-col"><col class="row-col"><col class="message-col"><col class="op-col"><col class="action-col"><col class="payload-col"></colgroup>' in html
    assert 'id="recentSelectAll"' in html
    assert '<th class="time-col">時間（本機）</th>' in html
    assert '<th class="file-col">檔案</th>' in html
    assert '<td class="select-col">${selectionCell(r)}</td>' in html
    assert '<td class="time-col">${formatAuditTime(r.processed_at)}</td>' in html
    assert '<td class="file-col" title="${escapeHtml(r.source_file)}">${escapeHtml(r.source_file)}</td>' in html
    assert '<th class="op-col">操作來源</th>' in html
    assert '<td class="op-col">${operatorSourceCell(r)}</td>' in html
    assert '#recent.operator-source-hidden col.op-col, #recent.operator-source-hidden th.op-col, #recent.operator-source-hidden td.op-col { display:none; }' in html
    assert "function syncOperatorSourceVisibility()" in html
    assert "table.classList.toggle('operator-source-hidden', !state.canDelete)" in html
    assert "syncOperatorSourceVisibility();" in html


def test_dashboard_header_shows_current_logged_in_user():
    html = dashboard_source()

    assert '<div id="whoami" class="header-user">未登入</div>' in html
    assert "async function loadCurrentUser()" in html
    assert (
        "fetch('/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } })"
        in html
    )
    assert "`${user.username} (${user.role || '-'})`" in html
    assert "await loadCurrentUser(); await loadTasks(); await loadDashboard();" in html
    assert html.count("function closeDestinationTableDropdown(") == 1


def test_dashboard_accepts_import_record_deep_link_filters():
    html = dashboard_source()

    assert "function applyInitialQueryParams()" in html
    assert "new URLSearchParams(window.location.search || '')" in html
    assert "source_file_filter: 'sourceFileFilter'" in html
    assert "config: 'config'" in html
    assert 'id="recentAuditSection"' in html
    assert (
        "resetDefaultWindow(); applyInitialQueryParams(); await loadCurrentUser(); await loadTasks(); applyInitialQueryParams(); await loadDashboard();"
        in html
    )


def test_recent_audit_batch_delete_and_report_download_controls():
    html = dashboard_source()

    assert "批次刪除勾選 SQL 列" in html
    assert "下載批次刪除報告 Excel" in html
    assert "function selectedDeletableRows()" in html
    assert "function batchDeleteConfirmationPhrase(rowCount)" in html
    assert "function confirmBatchDeleteRows(rows)" in html
    assert "請完整輸入" in html
    assert "DELETE ${rowCount}" in html
    assert "批次刪除需要填寫原因" in html
    assert "最後確認" in html
    assert "function deleteSelectedImportedRows()" in html
    assert "function downloadBatchDeleteReport()" in html
    assert "data-recent-delete-check" in html
    assert "/v1/excel-to-sql/delete-rows" in html
    assert "application/vnd.ms-excel" in html
    assert "deleted_row_payloads" in html


def test_delete_row_uses_audit_row_config_and_alerts_messages():
    html = dashboard_source()

    assert "function showError(text)" in html
    assert "alert(text)" in html
    assert "function rowConfigPath(row)" in html
    assert "function operatorSourceCell(r)" in html
    assert "來源任務：${escapeHtml(sourceConfig" in html
    assert "SQL table：${escapeHtml(destination" in html
    assert "⚠ 與上方任務不同" in html
    assert "row?.source_config_path" in html
    assert "row?.row_payload?.config_path" not in html
    assert "這筆 audit 事件的來源任務設定檔是" in html
    assert "將改用 audit 事件的來源任務刪除對應 SQL table" in html
    assert "body: JSON.stringify({ config: deleteConfig || $('config').value, hash_value: hashValue, reason })" in html
    assert "data-config-path" in html
    assert "data-destination-table" in html
    assert "state.canDelete = Boolean(data.can_delete)" in html
    assert "批次刪除只能勾選同一個來源任務設定檔" in html
    assert "body: JSON.stringify({ config: deleteConfig, hash_values: rows.map(item => item.hash_value), reason: reason.trim() })" in html


def test_sql_source_editor_page_and_navigation_are_wired():
    editor_html = (STATIC_ROOT / "editor.html").read_text(encoding="utf-8")
    bootstrap_js = (STATIC_ROOT / "editor_bootstrap.js").read_text(encoding="utf-8")
    source_html = (STATIC_ROOT / "excel_to_sql_source_editor.html").read_text(encoding="utf-8")
    source_js = (STATIC_ROOT / "excel_to_sql_source_editor_app.js").read_text(encoding="utf-8")

    assert "SQL 來源資料編輯器" in editor_html
    assert "SQL 來源資料統計儀表板" in editor_html
    assert "excelSourceDashboardBtn" in editor_html
    assert "excelSourceEditorBtn" in editor_html
    assert "20260703-agent-data-flow-nav" in editor_html
    assert "location.href = '/excel-to-sql-source-editor'" in bootstrap_js
    assert "location.href = '/excel-to-sql-source-dashboard'" in bootstrap_js
    assert "rememberEditorTokenForNavigation" not in bootstrap_js
    assert "sessionStorage.setItem('sra_editor_token', token)" not in bootstrap_js
    assert "sra_token" not in bootstrap_js
    assert "受控 SQL 來源資料表" in source_html
    assert "scope-help-tooltip" in source_html
    assert "sourceEditorScopeHelpText" in source_html
    assert "20260703-audit-metadata" in source_html
    assert '載入筆數上限' not in source_html
    assert 'id="sourceLimit"' not in source_html
    assert "/v1/excel-to-sql/source-rows" in source_js
    assert "/v1/excel-to-sql/source-row" in source_js
    source_dashboard_js = (STATIC_ROOT / "excel_to_sql_source_dashboard_app.js").read_text(encoding="utf-8")
    assert "const user=me.user||me||{}" in source_dashboard_js
    assert "${user.username}（${user.role||'-'}）" in source_dashboard_js
    assert "function authToken()" in source_js
    assert "function authToken() { return localStorage.getItem(tokenKey) || ''; }" in source_js
    assert "sessionStorage.getItem(tokenKey)" not in source_js
    assert "const loadMe = loadCurrentUser" in source_js
    assert "sra_token" not in source_js
    assert '<label for="usernameSummary">匯入使用者</label>' in source_html
    assert '<script src="/static/audit_tools.js"></script>' in source_html
    assert "SraAuditTools.renderMultiFilterOptions" in source_js
    assert "getPageSize: () => state.pageSize" in source_js
    assert "maxPageSize: 50000" in source_js
    assert "limit: String(Math.max(1, Math.min(50000, Number(state.pageSize || 50))))" in source_js
    assert "sourceLimit" not in source_js
    assert "params.append('username_filter', value)" in source_js
    assert "import_start_ts" in source_js
    assert "import_end_ts" in source_js
    assert "來源 Excel 包含" in source_html
    assert "匯入執行起" in source_html
    assert "批次刪除勾選 SQL 列" in source_html
    assert "function deleteSourceRow" in source_js
    assert "function confirmBatchDeleteRows" in source_js
    assert "data-source-delete-check" in source_js
    assert 'id="sourceSelectAll"' in source_js
    assert "function toggleSourceSelection(checked)" in source_js
    assert "selectAllBox.indeterminate" in source_js
    assert ">批刪<" not in source_js
    assert "displayColumnName(name)" in source_js
    assert "col-import-user" in source_html
    assert "此操作不會自動同步 ES" in source_html


def test_excel_flow_child_pages_use_editor_global_navigation_entry_only():
    page_names = [
        "excel_to_sql_dashboard.html",
        "excel_to_sql_import_center.html",
        "excel_to_sql_task_configs.html",
        "excel_to_sql_source_editor.html",
        "excel_to_sql_source_dashboard.html",
    ]
    sibling_routes = [
        "/excel-to-sql-dashboard",
        "/excel-to-sql-source-editor",
        "/excel-to-sql-source-dashboard",
        "/excel-to-sql-import-center",
        "/excel-to-sql-task-configs",
    ]
    for page_name in page_names:
        html = (STATIC_ROOT / page_name).read_text(encoding="utf-8")
        header = html.split("<header", 1)[1].split("</header>", 1)[0]
        for route in sibling_routes:
            assert route not in header, f"{page_name} should not show sibling nav route {route}"
        assert "/agent-data-flow" not in header
        assert "代理人資料流程圖" not in header
        assert "前往登入 / 編輯器" in header
        assert "主編輯器" not in header


def test_agent_data_flow_page_explains_agent_es_and_excel_sql_pipeline():
    html = (STATIC_ROOT / "agent_data_flow.html").read_text(encoding="utf-8")
    assert "代理人資料運用處理流程" in html
    assert "Elasticsearch" in html
    assert "txt 文本" in html
    assert "SQL 資料" in html
    assert "Excel→SQL 機制" in html
    assert "SQL→ES 匯入" in html
    assert "標準化中介" in html
    assert "使用者提問" in html
    assert "RAG" in html
    assert "回傳報告" in html
    assert "<img" in html
    assert "/excel-to-sql-dashboard" in html
    assert "/editor" in html
    response = TestClient(app).get("/agent-data-flow")
    assert response.status_code == 200
    assert "代理人資料運用處理流程" in response.text


def test_editor_navigation_links_agent_data_flow_page():
    html = (STATIC_ROOT / "editor.html").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "editor_bootstrap.js").read_text(encoding="utf-8")
    assert 'id="agentDataFlowBtn"' in html
    assert "代理人資料流程圖" in html
    assert "location.href = '/agent-data-flow'" in js
