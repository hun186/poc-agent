from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parents[1] / "sra_api" / "static"
DASHBOARD_HTML = STATIC_ROOT / "excel_to_sql_dashboard.html"
DASHBOARD_JS = STATIC_ROOT / "excel_to_sql_dashboard_app.js"


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


def test_dashboard_refresh_and_audit_filters_preserve_explicit_time_range():
    html = dashboard_source()

    assert 'id="endTs" type="datetime-local" step="1"' in html
    assert "function fillRecentWindow()" in html
    assert "function resetDefaultWindow()" in html
    assert "使用回看天數" not in html
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
    assert "#recent th.payload-col, #recent td.payload-col { width:41%; min-width:680px; }" in html
    assert '<colgroup><col class="select-col"><col class="time-col"><col class="status-col"><col class="file-col"><col class="user-col"><col class="row-col"><col class="message-col"><col class="action-col"><col class="payload-col"></colgroup>' in html
    assert 'id="recentSelectAll"' in html
    assert '<th class="time-col">時間（本機）</th>' in html
    assert '<th class="file-col">檔案</th>' in html
    assert '<td class="select-col">${selectionCell(r)}</td>' in html
    assert '<td class="time-col">${formatAuditTime(r.processed_at)}</td>' in html
    assert '<td class="file-col" title="${escapeHtml(r.source_file)}">${escapeHtml(r.source_file)}</td>' in html


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
