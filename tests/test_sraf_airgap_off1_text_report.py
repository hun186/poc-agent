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


def test_specific_off4_remediation_is_closed_vocab_without_native_reason():
    cases = (
        ("sql_constant_read", "SKIP", "sql_read_driver_unavailable", "ODBC Driver 18"),
        ("sql_constant_read", "SKIP", "sql_read_connection_unverified", "不得停用 TLS"),
        ("sql_constant_read", "FAIL", "sql_read_response_invalid", "固定常數查詢"),
        ("es_strict_tls_mapping", "FAIL", "es_tls_identity_failed", "數字 IP SAN"),
        ("es_strict_tls_mapping", "FAIL", "es_mapping_failed", "必要欄位"),
        ("es_strict_tls_mapping", "SKIP",
         "es_tls_mapping_observed_auth_not_verified", "Basic 認證已獨立驗證"),
        ("api_listener", "SKIP", "api_listener_unverified", "禁止傳送 Bearer"),
        ("worker_process_identity", "SKIP", "worker_process_identity_unverified", "PID namespace"),
    )
    for check, status, reason, expected in cases:
        evidence = {"result": "INCOMPLETE", "checks": [
            {"check": check, "status": status, "reason": reason}
        ]}
        txt = render_text_report(evidence).decode("utf-8")
        assert expected in txt
        assert reason not in txt
        assert txt.count("NOT_TESTED") == 8


def test_reason_guidance_requires_matching_check_status_and_exact_reason():
    evidence = {"result": "FAIL", "checks": [
        {"check": "sql_constant_read", "status": "FAIL",
         "reason": "sql_read_connection_unverified"},
        {"check": "sql_constant_read", "status": "SKIP",
         "reason": "sql_read_driver_unavailable SECRET_PASSWORD=do_not_echo"},
        {"check": "unrecognized", "status": "SKIP",
         "reason": "sql_read_driver_unavailable"},
        {"check": "sql_constant_read", "status": "SKIP",
         "reason": ["sql_read_driver_unavailable"]},
        {"check": "es_strict_tls_mapping", "status": "FAIL",
         "reason": {"es_tls_identity_failed": "token-secret"}},
    ]}
    txt = render_text_report(evidence).decode("utf-8")
    assert "ODBC Driver 18 已安裝" not in txt
    assert "先核對現有 CA" not in txt
    assert "SECRET_PASSWORD" not in txt and "token-secret" not in txt
    assert "未識別的檢查" in txt
    assert txt.count("NOT_TESTED") == 8


def test_reason_guidance_cannot_upconvert_pass_or_manual_gates():
    txt = render_text_report({"result": "PASS_PARTIAL", "checks": [
        {"check": "sql_constant_read", "status": "PASS",
         "reason": "sql_read_response_invalid"},
        {"check": "es_strict_tls_mapping", "status": "SKIP",
         "reason": "es_mapping_failed"},
    ], "manual_gates": [{"check": "physical_airgap", "status": "PASS"}]}).decode("utf-8")
    assert "固定常數查詢回應" not in txt
    assert "索引 Mapping 與必要欄位" not in txt
    assert "NOT_TESTED" in txt
    assert "完整斷網驗收證明" in txt
