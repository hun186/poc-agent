from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parents[1] / "api" / "static"
DASHBOARD_HTML = STATIC_ROOT / "excel_to_sql_dashboard.html"
DASHBOARD_JS = STATIC_ROOT / "excel_to_sql_dashboard.js"


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
    assert '<button onclick="refreshDashboardNow()">重新整理</button>' in html
    assert (
        "function applyAuditFilters() { resetRecentPage(); loadDashboard(); }"
        in html
    )
    assert "function refreshDashboardNow() { loadDashboard(); }" in html
    assert "回看天數（起迄皆空時才生效）" in html


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
