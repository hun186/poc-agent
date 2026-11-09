"""Human-readable, offline-safe Chinese triage for layered SRAF observations.

This is *presentation only*: status/authority come from real OFF-1 probes.
Unknown or malformed evidence is never promoted to a successful state.
No addresses, credentials, IDs, SQL or underlying exception strings are shown.
"""
from __future__ import annotations

from collections import Counter

LABELS = {
    "L0.target_platform": ("作業系統／ODBC 靜態環境", "僅檢查平台與檔案資訊，不等於原生 ODBC 載入或 SQL TLS 成功"),
    "L0.direct_distribution_metadata": ("Python 相依套件", "僅觀察 Metadata；不等於實際匯入或相依閉包成功"),
    "L0.static_launchers": ("Python／Uvicorn 啟動器", "檢查目前 Shell 的靜態啟動器，不驗證運行中服務是否使用相同環境"),
    "L0.host_disk": ("主機磁碟空間", "檢查預設最低空間門檻，不涵蓋每個報告儲存位置"),
    "L0.worker_process_identity": ("Schedule／Handoff Worker 身分", "核對啟動器紀錄與目前程序的一致性，未測試業務執行"),
    "L0.api_listener_preflight": ("API Listener 身分前置檢查", "檢查基本前置條件，未執行 Socket 全域排他證明"),
    "L1.api_tcp": ("API 連線", "有界本機 TCP 連線檢測，未驗證 API 身分或完整功能"),
    "L1.api_health": ("API /healthz", "匿名 GET /healthz HTTP 檢查，不驗證業務端點或權限"),
    "L1.es_tcp": ("Elasticsearch 連線", "僅檢查 TCP 連線，不驗證 TLS 憑證、身分、Mapping 或實際搜尋"),
    "L1.llm_tcp": ("LLM 連線", "僅檢查 TCP 連線，不驗證模型、推論品質或回應格式"),
    "L2.sql_constant_read": ("SQL Server 唯讀連線", "專用帳號固定常數 SELECT 檢查，不等於 Schema／業務查詢驗收"),
    "L2.es_tls_mapping": ("ES TLS／索引 Mapping", "既有 HTTPS／Mapping 的嚴格檢查，不包含獨立認證負向控制"),
    "L2.llm_inference": ("LLM 真實推論", "針對既有受控本機 Ollama 的推論檢查，不等於正式 Agent 生成能力"),
    "L3.report_job_docx": ("Report Job／Word DOCX", "針對單筆 Report Job 與 DOCX 的測試，不等於排程鏈完整驗收"),
    "L3.requirement_schedule_handoff_e2e": ("Requirement 自動排程完整 E2E", "透過真實 Harness 驗證受控工作鏈；不包含斷網、發行包或備份還原驗收"),
}
STATUS = {
    "PASS": "正常",
    "PASS_PARTIAL": "部分確認",
    "WARN": "警告",
    "FAIL": "失敗",
    "INCOMPLETE": "待確認",
    "SKIP": "未完成",
    "NOT_TESTED": "未執行",
}
FOCUS = ("FAIL", "WARN", "INCOMPLETE", "SKIP")
PRIORITY = {"FAIL": 0, "WARN": 1, "INCOMPLETE": 2, "SKIP": 3}

# Reasons are *fixed* and selected only after the underlying source supplied
# a known safe code. Never append raw exceptions, argv or environment values.
EXPLANATION = {
    "worker_process_identity_unverified": "無法將已記錄的 Worker 身分與目前程序匹配；不等於兩個 Worker 均已停止",
    "host_disk": "磁碟不足可能影響 DOCX、證據或報告產生",
    "disk_space_low": "低於既有磁碟最低門檻",
    "configured_tcp_connected": "已建立有界 TCP 連線",
    "healthz_http_200": "已收到 HTTP 200",
    "configured_tcp_unavailable": "未能建立有界 TCP 連線",
    "api_listener_prerequisite_unverified": "API 身分前置條件仍有未核實項目；不等於 API 已停止",
    "es_tls_identity_failed": "ES TLS 同儕身分驗證失敗，不能停用驗證",
    "es_mapping_failed": "ES 索引 Mapping 驗證失敗",
    "sql_read_connection_unverified": "無法完成受控 SQL 常數查詢",
    "sql_read_config_invalid": "專用 SQL 測試設定未通過驗證",
    "model_inventory_auth_required": "LLM 模型清單要求認證，未執行推論",
    "llm_inference_cloud_disable_unverified": "未能證實受控本機 Ollama／停用雲端條件",
    "prerequisites_not_verified": "更高層測試的必要前置條件未通過，未啟動此測試",
    "report_job_acceptance_incomplete": "Report Job 驗收證據不足，不能認定成功或失敗",
    "requirement_e2e_harness_failed": "完整 E2E Harness 回報失敗，請在機器內檢查私有測試證據",
    "e2e_private_environment_unverified": "E2E 私有設定檔不存在、權限或所有者不符合要求",
    "probe_unavailable": "元件探針未能提供可信結果",
    "runtime_config_unavailable": "無法安全解析應用程式執行設定",
    "runtime_probe_unavailable": "無法取得完整執行環境觀察",
}

REMEDIATION = {
    "L0.worker_process_identity": (
        "先觀察是否處於部署／Worker 啟動切換期間；若重複發生，核對既有 "
        ".run_sra_api_schedule.identity 與 .run_sra_api_handoff.identity 的存在、"
        "所有權、啟動時間及與 /proc 的 UID／工作目錄／角色是否一致。"
        "驗證器由 Schedule 開始，一旦第一項失敗就停止，0/2 不能解讀為兩個都掛掉。"
        "不要直接覆寫紀錄、殺程序或放寬檢查。"),
    "L0.target_platform": "檢查部署 Python／ODBC 18 驅動安裝與版本選取；原生載入仍需另外驗證。",
    "L0.direct_distribution_metadata": "檢查應用程式實際使用的 Python 環境與相依套件，必要時執行獨立 import 測試；勿直接重新安裝。",
    "L0.static_launchers": "核對目前 Shell 的 Python、Uvicorn 啟動器與實際服務啟動環境，避免直接重啟。",
    "L0.host_disk": "檢查受影響檔案系統的剩餘空間及容量配置，避免直接清除既有報告／稽核資料。",
    "L0.api_listener_preflight": "核對由啟動器管理的 API 身分紀錄及 Listener 前置條件；完整排他身分證明需另行授權。",
    "L1.api_tcp": "確認 API 是否在部署設定的本機 Port 監聽；不可僅因探針失敗直接重啟服務。",
    "L1.api_health": "檢查 API 本機 /healthz 是否回傳 200；TCP 通過不代表 FastAPI 應用準備完成。",
    "L1.es_tcp": "確認 ES 私有網路端點與服務狀態；接著需嚴格檢查 CA／IP SAN 和 Mapping，勿停用 TLS。",
    "L1.llm_tcp": "確認模型端點是否可用；TCP 正常後仍需獨立授權實際推論，避免影響在跑的批次。",
    "L2.sql_constant_read": "以專用最小權限測試帳號核對 ODBC/TLS 及固定 SELECT，不要使用正式高權限帳號繞過。",
    "L2.es_tls_mapping": "檢查可信 CA、IP SAN、既有索引 Mapping；勿停用 TLS 驗證或修改正式索引以求通過。",
    "L2.llm_inference": "確認受控 Ollama 程序、Socket、無雲端設定與模型清單，必要時錯開業務尖峰測試。",
    "L3.report_job_docx": "查看現有 OFF-1 Report Job 私有驗收證據，核對 Job 狀態、DOCX 完整性及服務授權。",
    "L3.requirement_schedule_handoff_e2e": (
        "在部署機私有 operator_e2e 輸出目錄檢查 summary.txt／result.json 的"
        "失敗階段；不得貼出 Token、完整路徑、業務資料或環境設定。"),
}


def _duration(value: object) -> str:
    if type(value) is int and 0 <= value <= 3_600_000:
        return f"{value} ms"
    return "未量測"


def _rows(report: dict[str, object]) -> list[dict[str, object]]:
    raw = report.get("checks", [])
    if not isinstance(raw, list) or len(raw) > len(LABELS):
        return []
    result = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict):
            return []
        name, status = row.get("id"), row.get("status")
        if name not in LABELS or name in seen or status not in STATUS:
            return []
        seen.add(name)
        result.append(row)
    return result


def render_report(report: dict[str, object]) -> str:
    """Explain observed evidence, not make new success or incident claims."""
    rows = _rows(report)
    if not rows or len(rows) != len(LABELS):
        return ("SRAF 分層診斷報告\n"
                "判定：待確認；診斷報告格式不完整，不能認定元件正常。\n"
                "請由維護人員檢查診斷程式完整性；不應逕行修改正式系統。\n")
    counts = Counter(str(x["status"]) for x in rows)
    selected = [r for r in rows if r["status"] != "NOT_TESTED"]
    warnings = sorted((r for r in selected if r["status"] in FOCUS),
                      key=lambda row: (PRIORITY[row["status"]],
                                       row["id"]))
    level = report.get("level") if report.get("level") in ("L0", "L1", "L2", "L3") else "UNKNOWN"
    overall = report.get("status") if report.get("status") in STATUS else "INCOMPLETE"

    lines = [
        "=" * 64,
        "SRAF 部署機維護診斷報告（本機可獨立判讀）",
        f"執行層級：{level}   綜合判定：{STATUS[overall]} ({overall})",
        "注意：此判定僅涵蓋本次選定的檢查，不能等同正式上線或 FULL_LIVE 驗收。",
        f"已執行：{len(selected)} 項；需釐清：{len(warnings)} 項；"
        f"未選用／未執行：{counts['NOT_TESTED']} 項。",
        "",
        "【一、元件實際觀察結果】",
    ]
    for row in rows:
        name, state = row["id"], row["status"]
        label, scope = LABELS[name]
        detail = EXPLANATION.get(row.get("reason"), "")
        # Never print arbitrary reason/exception text; only known fixed prose.
        if not detail:
            detail = scope
        elif state in ("PASS", "PASS_PARTIAL") and detail != scope:
            detail = detail + "；" + scope
        lines.append(f"  [{STATUS[state]}] {label}：{detail}（{_duration(row.get('elapsed_ms'))}）")
    lines += ["", "【二、需維護人員確認的項目（按嚴重程度）】"]
    if warnings:
        for index, row in enumerate(warnings, 1):
            label = LABELS[row["id"]][0]
            lines.append(f"  {index}. [{STATUS[row['status']]}] {label}")
            lines.append(f"     觀察：{EXPLANATION.get(row.get('reason'), '現有證據不足，無法驗證此項功能。')}")
            lines.append(f"     建議：{REMEDIATION[row['id']]}")
    else:
        lines.append("  本次已執行的檢查沒有失敗／警告／未核實項目；仍須留意各項驗證範圍。")
    lines += [
        "",
        "【三、維護結論與驗收邊界】",
    ]
    by_id = {x["id"]: x["status"] for x in rows}
    if by_id.get("L1.api_health") == "PASS":
        lines.append("  • API /healthz 已回傳 200；代表基本 HTTP 健康檢查正常。")
    else:
        lines.append("  • API 健康狀態尚未通過 HTTP 200 確認，不能判定正常。")
    for key, label in (("L1.es_tcp", "Elasticsearch"), ("L1.llm_tcp", "LLM")):
        lines.append(f"  • {label}：" +
                     ("TCP 連線可達；不是實際功能驗收。"
                      if by_id.get(key) == "PASS" else "連線未確認或未通過；功能狀態待驗證。"))
    worker = by_id.get("L0.worker_process_identity")
    if worker == "INCOMPLETE":
        lines.append("  • Worker：程序身分未核實；不能由此斷言兩個 Worker 都停止或自動排程已失效。")
    if by_id.get("L2.sql_constant_read") == "NOT_TESTED":
        lines.append("  • SQL Server：本次未執行 SQL 功能測試。")
    if (by_id.get("L3.requirement_schedule_handoff_e2e") == "NOT_TESTED"
            and by_id.get("L3.report_job_docx") == "NOT_TESTED"):
        lines.append("  • 完整報告鏈：本次未執行 Report Job 或自動排程 E2E。")
    lines += [
        "  • 即使全部有限檢查通過，也不代表 ODBC 原生載入、ES TLS／Mapping、"
        "LLM 推論、SQL 權限、Word、物理斷網或備份還原都已驗收。",
        "  • 不需聯外、不需提供對話截圖；可由維護人員直接根據上述結論處置。",
        "=" * 64,
    ]
    return "\n".join(lines) + "\n"
