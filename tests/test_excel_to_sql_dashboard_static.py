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
