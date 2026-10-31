"""OFF-4 redacted human report: no private data, no runtime dependencies."""
from tools.sraf_airgap_off1_text_report import render_text_report


def test_render_off4_closed_vocabulary_and_manual_gates():
    observed = {
        "result": "PASS_PARTIAL",
        "suite": "diagnose",
        "network_mode": "NONE",
        "completed_at_utc": "2026-10-31T03:00:00+00:00",
        "manual_gates": [{"check": "physical_airgap", "status": "PASS"}],
        "checks": [
            {"check": "host_disk", "status": "PASS", "reason": "disk_threshold_met"},
            {"check": "sql_constant_read", "status": "SKIP",
             "reason": "PRIVATE_DB=prod;PASSWORD=topsecret"},
        ],
        "secret": "LEAK_TOKEN_123",
    }
    raw = render_text_report(observed)
    txt = raw.decode("utf-8")
    assert "2026-10-31T03:00:00+00:00" in txt
    assert "網路：停用" in txt
    assert "SQL TLS 常數查詢" in txt
    assert "證據不足／跳過" in txt
    assert txt.count("NOT_TESTED") == 8
    assert "完整斷網驗收" in txt
    for secret in ("PASSWORD", "topsecret", "LEAK_TOKEN", "prod"):
        assert secret not in txt


def test_render_off4_malformed_values_fail_closed_and_redacted():
    ev = {"result": ["PASS_PARTIAL"], "suite": "secret",
          "network_mode": "secret", "completed_at_utc": "bad\nLEAK",
          "checks": [
              {"check": "SECRET_HOST_IP", "status": ["PASS"],
               "reason": "LEAK_NATIVE_SQLSTATE"},
              None,
              {"check": "operator", "status": {"PASS": "yes"},
               "reason": "USER_PASSWORD_LEAK"},
          ]}
    txt = render_text_report(ev).decode("utf-8")
    assert "INCOMPLETE" in txt
    assert "未提供" in txt
    assert "未識別的檢查" in txt
    for secret in ("SECRET_", "LEAK", "PASSWORD", "SQLSTATE"):
        assert secret not in txt
    assert "正式上線" in txt


def test_render_off4_bounded_rows():
    ev = {"result": "FAIL", "checks": [
        {"check": "api_health", "status": "FAIL", "reason": "never rendered"}
        for _ in range(100)
    ]}
    txt = render_text_report(ev).decode("utf-8")
    assert txt.count("SRAF API 健康檢查") == 64
    assert "其餘檢查未列出" in txt
    assert "never rendered" not in txt
