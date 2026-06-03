from pathlib import Path


DASHBOARD_HTML = (
    Path(__file__).resolve().parents[1] / "api" / "static" / "excel_to_sql_dashboard.html"
)


def test_chart_bucket_selector_is_visible_in_chart_card_and_sent_to_api():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert '<label for="chartBucket">曲線圖時間區間</label>' in html
    assert html.count('id="chartBucket"') == 1
    assert 'aria-label="曲線圖時間區間設定"' in html
    assert "chart_bucket: $('chartBucket').value" in html
    assert "$('chartBucket').addEventListener('change', applyAuditFilters)" in html


def test_dashboard_refresh_and_audit_filters_extend_end_time_to_now():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert 'id="endTs" type="datetime-local" step="1"' in html
    assert 'function updateEndTsToNow()' in html
    assert 'Date.now() + 60 * 1000' in html
    assert '<button onclick="refreshDashboardNow()">重新整理</button>' in html
    assert 'function applyAuditFilters() { resetRecentPage(); updateEndTsToNow(); loadDashboard(); }' in html
    assert 'updateEndTsToNow();\n  await loadDashboard();' in html


def test_recent_audit_filters_include_destination_table():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert '<label>目的地 table</label><select id="destinationTableFilter" multiple size="4">' in html
    assert '可按 Ctrl / Command 複選' in html
    assert "selectedValues('destinationTableFilter').forEach" in html
    assert "params.append('destination_table_filter', value)" in html
    assert 'function renderDestinationTableOptions(options)' in html
    assert "renderDestinationTableOptions(data.destination_table_options || [])" in html
    assert "'destinationTableFilter'" in html
