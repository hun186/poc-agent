"""Redacted, offline, operator-readable TXT companion for OFF-1 hub JSON.

Only closed vocabulary strings enter this report. Never embed native errors,
probe payloads, credentials, endpoint names, PID, Job IDs, or arbitrary paths.
No file/network access here: the caller owns secure dirfd writes.
"""
from __future__ import annotations

import re

CHECKS = {
    "host_disk": ("本機磁碟空間", "確認可用空間與掛載權限"),
    "host_odbc_library": ("ODBC 原生函式庫", "確認已離線安裝正確版本的 ODBC 驅動"),
    "api_health": ("SRAF API 健康檢查", "檢查 API 程序、啟動日誌與本機監聽"),
    "ui_page": ("瀏覽器頁面", "檢查已部署的靜態頁面與 API 服務"),
    "ui_javascript": ("瀏覽器腳本", "確認部署產物完整、靜態檔案存在"),
    "ui_stylesheet": ("瀏覽器樣式", "確認部署產物完整、靜態檔案存在"),
    "api_listener": ("API 監聽者身分", "核對啟動器紀錄、PID namespace 與 /proc 可見性"),
    "worker_process_identity": ("Schedule/Handoff 程序身分", "核對工作程序與目前容器 PID namespace"),
    "tcp_api": ("API TCP 可達性", "檢查 API 監聽與本機防火牆"),
    "tcp_es": ("Elasticsearch TCP 可達性", "檢查內網 ES 位址、連線設定及防火牆"),
    "tcp_llm": ("LLM TCP 可達性", "檢查內網模型服務及容器網路"),
    "es_strict_tls_mapping": ("ES TLS 與 Mapping 限定檢查", "檢查 CA、數字 IP SAN 與索引 Mapping；仍需獨立認證驗收"),
    "sql_constant_read": ("SQL TLS 常數查詢", "檢查專用帳號、ODBC 18、TLS 識別與資料庫連通；不代表 Schema 通過"),
    "authentication": ("操作員身分驗證", "檢查操作員授權與嚴格 API listener 身分"),
    "live_report": ("真實報告操作", "僅在獲得明確授權後檢查 Report Job 先決條件"),
    "report_docx": ("Word 文件完整性", "檢查實際授權的報告執行與 DOCX 檔案"),
    "operator": ("操作環境", "檢查已部署依賴、配置與安全輸出目錄"),
}
MANUAL_GATES = {
    "es_tls_ca_san_mapping": "完整 ES TLS／認證／Mapping",
    "sql_schema_source_permissions": "SQL Schema／來源／權限",
    "schedule_handoff_workers": "Schedule／Handoff 實際工作",
    "real_agent_llm_es": "真實 Agent／LLM／ES 報告",
    "browser_visual": "實際瀏覽器檢視",
    "package_release_provenance": "離線發行包來源與版本",
    "backup_restore_off5": "備份及還原演練",
    "physical_airgap": "實體封閉網路驗收",
}

# Only exact (check, status, canonical-reason) triples can change the advice.
# A reason is never printed, and arbitrary/invalid values use CHECKS fallback.
# Keep the mapping intentionally small; additions require review and tests.
REASON_GUIDANCE = {
    ("sql_constant_read", "SKIP", "sql_read_config_invalid"):
        "檢查操作員專用 SQL 測試環境變數；不得改用正式 Registry 密碼",
    ("sql_constant_read", "SKIP", "sql_read_driver_unavailable"):
        "先在離線主機確認 ODBC Driver 18 已安裝；不可為診斷而連線下載套件",
    ("sql_constant_read", "SKIP", "sql_read_connection_unverified"):
        "查核內網 SQL 連線、CA／IP SAN 與專用最小權限帳號；不得停用 TLS 憑證驗證",
    ("sql_constant_read", "FAIL", "sql_read_response_invalid"):
        "固定常數查詢回應不符合預期；核對驅動與受控查詢端點，不可視為 Schema 已驗證",
    ("es_strict_tls_mapping", "FAIL", "es_tls_identity_failed"):
        "先核對現有 CA 與 Elasticsearch 端點的數字 IP SAN；禁止改成忽略 TLS 身分",
    ("es_strict_tls_mapping", "FAIL", "es_https_identity_failed"):
        "檢查受控 HTTPS 端點與憑證身分；不可透過 HTTP 或不驗證憑證繞過失敗",
    ("es_strict_tls_mapping", "FAIL", "es_auth_rejected"):
        "確認受控 ES 測試身分具足夠唯讀權限；勿反覆嘗試錯誤密碼",
    ("es_strict_tls_mapping", "FAIL", "es_mapping_failed"):
        "由授權人員核對索引 Mapping 與必要欄位；診斷模式不會重建索引",
    ("es_strict_tls_mapping", "SKIP", "es_tls_mapping_observed_auth_not_verified"):
        "TLS 與 Mapping 可觀察，不代表 Basic 認證已獨立驗證；完整驗收仍須另外授權",
    ("api_health", "SKIP", "network_disabled"):
        "本次選用不開網路連線，不能判定 API 是否可達；依需求重新選擇檢查模式",
    ("api_listener", "SKIP", "api_listener_unverified"):
        "核對啟動器 PID 身分紀錄與 /proc 可見性；無嚴格身分證據時禁止傳送 Bearer",
    ("worker_process_identity", "SKIP", "worker_process_identity_unverified"):
        "Schedule/Handoff 程序可能在其他 PID namespace；檢查容器可見性及啟動紀錄",
    ("live_report", "SKIP", "prerequisite_checks_not_passed"):
        "先排除先決檢查失敗；未驗證前不可提交真實報告或擴大授權",
    ("operator", "SKIP", "operator_environment_or_transport_unavailable"):
        "檢查應用 Python 相依、部署設定與安全輸出目錄，勿貼出完整環境變數或例外",
}

STATUS = {"PASS": "通過", "FAIL": "失敗", "WARN": "警告", "SKIP": "證據不足／跳過"}
RESULT = {"PASS_PARTIAL": "部分檢查通過", "FAIL": "存在已確認失敗", "INCOMPLETE": "未能完成所選檢查"}


def render_text_report(evidence: dict) -> bytes:
    """Return bounded UTF-8 without interpolating untrusted evidence values."""
    result = evidence.get("result")
    if not isinstance(result, str) or result not in RESULT:
        result = "INCOMPLETE"
    raw_time = evidence.get("completed_at_utc")
    timestamp = (raw_time if isinstance(raw_time, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", raw_time
    ) else "未提供")
    suite = {"quick": "快速檢查", "diagnose": "診斷"}.get(
        evidence.get("suite") if isinstance(evidence.get("suite"), str) else None,
        "未確認",
    )
    network = {"NONE": "停用", "BOUNDED_LOCAL_ONLY": "限定內網／本機"}.get(
        evidence.get("network_mode") if isinstance(evidence.get("network_mode"), str) else None,
        "未確認",
    )
    lines = [
        "SRAF OFF-1 離線操作診斷摘要（脫敏 TXT）",
        "================================================",
        f"完成時間（UTC）：{timestamp}",
        f"模式：{suite}；網路：{network}",
        f"結論：{RESULT[result]}（{result}）",
        "注意：這是部分檢查，絕非正式上線／完整斷網驗收證明。",
        "",
        "一、已選擇的檢查（不含原始連線資訊）",
    ]
    rows = evidence.get("checks")
    if not isinstance(rows, list):
        rows = []
    for row in rows[:64]:
        if not isinstance(row, dict):
            lines.append("- 未知檢查：證據不足／跳過")
            continue
        key = row.get("check")
        details = CHECKS.get(key) if isinstance(key, str) else None
        label, advice = details if details else ("未識別的檢查", "使用原始受控 JSON 與專案文件人工核對")
        status = row.get("status")
        if not isinstance(status, str) or status not in STATUS:
            status = "SKIP"
        lines.append(f"- {label}：{STATUS[status]} [{status}]")
        if status != "PASS":
            reason = row.get("reason")
            if (details is not None and isinstance(reason, str)):
                advice = REASON_GUIDANCE.get((key, status, reason), advice)
            lines.append(f"  建議：{advice}")
    if len(rows) > 64:
        lines.append("- 其餘檢查未列出；請由授權工程師核對受控 JSON")
    lines.extend(("", "二、尚需獨立完成的正式驗收門檻"))
    for title in MANUAL_GATES.values():
        lines.append(f"- {title}：NOT_TESTED（未驗證）")
    lines.extend((
        "", "三、使用說明",
        "請由有權限的工程師在相同私有目錄檢查對應 JSON 的固定原因碼。",
        "本 TXT 不包含帳密、Token、主機位址、查詢內容、文件內容或原始例外。",
        "僅有實機授權、真實依賴與 OFF-2～5 演練才能完成完整驗收。",
        "",
    ))
    return "\n".join(lines).encode("utf-8")
