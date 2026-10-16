#!/usr/bin/env python3
"""Validate the OFF-0 air-gap acceptance inventory without external dependencies.

This command validates contract shape and check dependencies only. It never
connects to SQL/ES/LLM, starts workers, imports SRA runtime, or runs E2E.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import unicodedata
from pathlib import Path
from typing import Any


MODES = ("quick", "diagnose", "acceptance")
EFFECTS = frozenset({"read_only", "compute_only", "test_job_write"})
READINESS = frozenset({"existing_component", "existing_external_smoke", "planned"})
STATUSES = ("PASS", "FAIL", "WARN", "SKIP")
CHECK_KEYS = frozenset({
    "id", "title", "component", "minimum_mode", "effect", "readiness",
    "depends_on", "existing_evidence", "error_code", "remediation",
})
REPORT_FIELDS = frozenset({
    "check_id", "component", "status", "severity", "error_code", "summary",
    "evidence", "remediation", "dependency", "duration_ms",
})
ROOT_KEYS = frozenset({
    "schema_version", "issue", "scope", "default_mode", "modes",
    "valid_states", "effects", "report_required", "checks", "report_policy",
})
REPORT_POLICY_KEYS = frozenset({
    "strategy", "summary_source", "remediation_source",
    "allow_raw_exceptions", "allow_unstructured_evidence",
    "max_evidence_entries", "max_evidence_value_chars", "permitted_evidence",
})
PERMITTED_EVIDENCE = {
    "http_status": "http_status",
    "item_count": "nonnegative_integer",
    "accepted_count": "nonnegative_integer",
    "rejected_count": "nonnegative_integer",
    "file_count": "nonnegative_integer",
    "worker_count": "nonnegative_integer",
    "component_size_bytes": "nonnegative_integer",
    "package_sha256": "sha256",
    "provenance_fingerprint": "sha256",
    "artifact_sha256": "sha256",
    "identity_verified": "boolean",
    "mapping_compatible": "boolean",
    "model_available": "boolean",
    "classification": "classification",
}
SKIP_REASON_CODES = frozenset({
    "blocked_by_dependency", "check_not_implemented", "auth_session_unavailable",
    "mode_not_enabled",
})
# Reviewed fixed strings: the editable registry alone may not introduce report copy.
APPROVED_REPORT_TEXT = {
    "PKG-01": {
        "title": "發行包／部署檔案完整性",
        "remediation": "SHA-256 與執行中的受管理檔案不一致"
    },
    "SYS-01": {
        "title": "主機資源、磁碟與時間",
        "remediation": "檢查容量、時鐘及檔案權限"
    },
    "ENV-01": {
        "title": "Python 套件與離線 wheelhouse",
        "remediation": "比對已鎖定的版本、離線 wheelhouse 與依賴樹"
    },
    "ENV-02": {
        "title": "原生函式庫與 ODBC Driver",
        "remediation": "確認已離線安裝所需 ODBC driver 及 shared libraries"
    },
    "API-01": {
        "title": "SRA API Health",
        "remediation": "檢查本機 port、API 進程與啟動日誌"
    },
    "AUTH-01": {
        "title": "匿名資源存取拒絕",
        "remediation": "匿名請求應拒絕，不得建立登入 session"
    },
    "SQL-01": {
        "title": "SQL Server 唯讀連線",
        "remediation": "區分 DNS/driver/TLS/登入/權限問題；勿列印 connection string"
    },
    "SQL-02": {
        "title": "Requirement／Schedule Schema",
        "remediation": "比對既有 schema/catalog；不得執行 migration"
    },
    "ES-01": {
        "title": "Elasticsearch 連線與認證",
        "remediation": "檢查封閉網路端點與授權"
    },
    "ES-02": {
        "title": "索引 alias 與 Mapping 相容性",
        "remediation": "報告失配欄位；不得自動修改或重建索引"
    },
    "ES-03": {
        "title": "真實 ES 檢索結果",
        "remediation": "使用已確認的隔離索引及受控查詢驗證檢索"
    },
    "LLM-01": {
        "title": "模型與推論服務可用性",
        "remediation": "模型須事先下載；不呼叫外部網路"
    },
    "LLM-02": {
        "title": "真實模型小型推論",
        "remediation": "檢查服務資源、模型權重與上下文配置"
    },
    "WORK-01": {
        "title": "Schedule/Handoff Worker 身分",
        "remediation": "不得用 PID 是否存在取代帶身分的 worker 驗證"
    },
    "PROD-01": {
        "title": "Product P2.1 路由與讀取",
        "remediation": "驗證 route, read, 401/404/422；空清單不等於有資料的查詢成功"
    },
    "PREV-01": {
        "title": "真實 Excel Preview 不落地",
        "remediation": "確認 accepted/rejected 筆數與資料不落地"
    },
    "RUN-01": {
        "title": "Requirement→Schedule→Agent 完整 E2E",
        "remediation": "必須指定授權測試身分及專用 fixture，禁止由 Quick 啟動"
    },
    "DOC-01": {
        "title": "DOCX 與 SHA-256 驗證",
        "remediation": "驗證 docx ZIP、安全路徑、SHA-256，並獨立記錄內容品質"
    },
    "AIR-01": {
        "title": "封閉網路隔離證據",
        "remediation": "確認未使用 GitHub、pip index、ChatGPT、外部 LLM；只驗證被允許的內網相依"
    }
}

# In-code reviewed readiness authority: mutable JSON cannot self-upgrade probes.
# OFF-1 implementation must update this map only with reviewed probe evidence.
APPROVED_CHECK_READINESS = {
    "PKG-01": "existing_component",
    "SYS-01": "planned",
    "ENV-01": "planned",
    "ENV-02": "planned",
    "API-01": "existing_component",
    "AUTH-01": "existing_component",
    "SQL-01": "planned",
    "SQL-02": "planned",
    "ES-01": "existing_component",
    "ES-02": "existing_component",
    "ES-03": "planned",
    "LLM-01": "planned",
    "LLM-02": "existing_component",
    "WORK-01": "existing_component",
    "PROD-01": "planned",
    "PREV-01": "existing_external_smoke",
    "RUN-01": "existing_component",
    "DOC-01": "existing_component",
    "AIR-01": "planned",
}

# Approved check semantics are code-reviewed authority, not JSON configuration.
# Do not let mutable registry metadata silently downgrade an acceptance write
# into Quick mode or reroute failure attribution to a different component.
APPROVED_CHECK_SEMANTICS = {
    "PKG-01": {
        "component": "release",
        "minimum_mode": "quick",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "package_missing"
    },
    "SYS-01": {
        "component": "host",
        "minimum_mode": "quick",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "host_resource_insufficient"
    },
    "ENV-01": {
        "component": "host",
        "minimum_mode": "quick",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "python_dependency_missing"
    },
    "ENV-02": {
        "component": "host",
        "minimum_mode": "quick",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "odbc_driver_missing"
    },
    "API-01": {
        "component": "api",
        "minimum_mode": "quick",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "api_unreachable"
    },
    "AUTH-01": {
        "component": "auth",
        "minimum_mode": "quick",
        "effect": "read_only",
        "depends_on": [
            "API-01"
        ],
        "error_code": "auth_boundary_invalid"
    },
    "SQL-01": {
        "component": "sql",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [
            "ENV-02"
        ],
        "error_code": "sql_unreachable"
    },
    "SQL-02": {
        "component": "sql",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [
            "SQL-01"
        ],
        "error_code": "sql_schema_mismatch"
    },
    "ES-01": {
        "component": "elasticsearch",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "es_unreachable"
    },
    "ES-02": {
        "component": "elasticsearch",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [
            "ES-01"
        ],
        "error_code": "mapping_incompatible"
    },
    "ES-03": {
        "component": "elasticsearch",
        "minimum_mode": "acceptance",
        "effect": "read_only",
        "depends_on": [
            "ES-02"
        ],
        "error_code": "es_retrieval_invalid"
    },
    "LLM-01": {
        "component": "llm",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [],
        "error_code": "llm_model_missing"
    },
    "LLM-02": {
        "component": "llm",
        "minimum_mode": "acceptance",
        "effect": "compute_only",
        "depends_on": [
            "LLM-01"
        ],
        "error_code": "llm_inference_failed"
    },
    "WORK-01": {
        "component": "worker",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [
            "PKG-01",
            "API-01"
        ],
        "error_code": "worker_identity_unverified"
    },
    "PROD-01": {
        "component": "api",
        "minimum_mode": "diagnose",
        "effect": "read_only",
        "depends_on": [
            "API-01"
        ],
        "error_code": "product_api_invalid"
    },
    "PREV-01": {
        "component": "api",
        "minimum_mode": "acceptance",
        "effect": "compute_only",
        "depends_on": [
            "PROD-01"
        ],
        "error_code": "preview_normalization_failed"
    },
    "RUN-01": {
        "component": "workflow",
        "minimum_mode": "acceptance",
        "effect": "test_job_write",
        "depends_on": [
            "PKG-01",
            "SQL-02",
            "ES-03",
            "LLM-02",
            "WORK-01"
        ],
        "error_code": "workflow_acceptance_failed"
    },
    "DOC-01": {
        "component": "artifact",
        "minimum_mode": "acceptance",
        "effect": "read_only",
        "depends_on": [
            "RUN-01"
        ],
        "error_code": "docx_integrity_failed"
    },
    "AIR-01": {
        "component": "release",
        "minimum_mode": "acceptance",
        "effect": "read_only",
        "depends_on": [
            "PKG-01",
            "ENV-01",
            "ENV-02"
        ],
        "error_code": "airgap_isolation_unverified"
    }
}

REPORT_TEXT_FORBIDDEN = re.compile(
    r"(?i)(?:https?://|file://|www\.|"
    r"[a-z_]*(?:password|passwd|token|secret|credential|api[_-]?key)[a-z_]*\s*[:=]|"
    r"\bbearer\s+\S+|\btraceback\b|"
    r"\b[A-Za-z]*(?:Exception|Error)\s*[:(]|"
    r"(?:^|\s)/[a-zA-Z0-9._-]+(?:/[a-zA-Z0-9._-]+)*|"
    r"\b[A-Za-z]:[\\/])"
)


def _safe_report_text(value: Any, *, max_chars: int, code: str) -> None:
    _require(
        isinstance(value, str) and value == value.strip() and
        1 <= len(value) <= max_chars and
        all(unicodedata.category(ch) not in {"Cc", "Cf", "Zl", "Zp"}
            for ch in value) and
        REPORT_TEXT_FORBIDDEN.search(value) is None,
        code,
    )


class ContractError(ValueError):
    """A bounded validation error, safe to show in a terminal."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _validate_report_policy(policy: Any) -> None:
    _require(isinstance(policy, dict) and set(policy) == REPORT_POLICY_KEYS,
             "contract_report_policy_shape_invalid")
    _require(policy["strategy"] == "allowlisted_fields_fail_closed" and
             policy["summary_source"] == "inventory_check_title" and
             policy["remediation_source"] == "inventory_check_remediation" and
             policy["allow_raw_exceptions"] is False and
             policy["allow_unstructured_evidence"] is False and
             type(policy["max_evidence_entries"]) is int and
             policy["max_evidence_entries"] == 12 and
             type(policy["max_evidence_value_chars"]) is int and
             policy["max_evidence_value_chars"] == 80 and
             policy["permitted_evidence"] == PERMITTED_EVIDENCE,
             "contract_report_policy_unsafe")


def validate_contract(document: Any) -> int:
    _require(isinstance(document, dict), "contract_not_object")
    _require(set(document) == ROOT_KEYS, "contract_top_level_shape_invalid")
    _require(document.get("schema_version") == "sraf_airgap_off0_inventory_v1",
             "contract_schema_version_invalid")
    _require(type(document.get("issue")) is int and document["issue"] == 290,
             "contract_issue_invalid")
    _require(document.get("scope") == "contract_only_not_executable",
             "contract_scope_invalid")
    _require(document.get("default_mode") == "quick", "contract_unsafe_default")
    _require(document.get("modes") == list(MODES), "contract_modes_invalid")
    _require(document.get("valid_states") == list(STATUSES),
             "contract_states_invalid")
    effects = document.get("effects")
    required = document.get("report_required")
    _require(isinstance(effects, list) and
             all(isinstance(v, str) for v in effects) and
             len(effects) == len(EFFECTS) and set(effects) == EFFECTS,
             "contract_effects_invalid")
    _require(isinstance(required, list) and
             all(isinstance(v, str) for v in required) and
             len(required) == len(REPORT_FIELDS) and
             set(required) == REPORT_FIELDS,
             "contract_report_fields_invalid")
    _validate_report_policy(document["report_policy"])
    checks = document.get("checks")
    _require(isinstance(checks, list) and bool(checks),
             "contract_checks_missing")
    by_id: dict[str, dict[str, Any]] = {}
    for item in checks:
        _require(isinstance(item, dict) and set(item) == CHECK_KEYS,
                 "contract_check_shape_invalid")
        identifier = item["id"]
        _require(isinstance(identifier, str) and
                 re.fullmatch(r"[A-Z]{2,5}-[0-9]{2}", identifier) is not None,
                 "contract_check_id_invalid")
        _require(identifier not in by_id, "contract_duplicate_check_id")
        _safe_report_text(
            item["title"], max_chars=96, code="contract_report_text_unsafe",
        )
        _safe_report_text(
            item["remediation"], max_chars=200,
            code="contract_report_text_unsafe",
        )
        _require(APPROVED_REPORT_TEXT.get(identifier) == {
            "title": item["title"], "remediation": item["remediation"],
        }, "contract_report_text_unapproved")
        _require(isinstance(item["component"], str) and
                 re.fullmatch(r"[a-z][a-z0-9_]{0,31}",
                              item["component"]) is not None,
                 "contract_report_component_unsafe")
        _require(isinstance(item["error_code"], str) and
                 re.fullmatch(r"[a-z][a-z0-9_]{2,63}",
                              item["error_code"]) is not None,
                 "contract_report_error_code_unsafe")
        _require(isinstance(item["existing_evidence"], str) and
                 1 <= len(item["existing_evidence"]) <= 512 and
                 all(unicodedata.category(ch) not in {"Cc", "Cf", "Zl", "Zp"}
                     for ch in item["existing_evidence"]),
                 "contract_check_field_invalid")
        _require(isinstance(item["minimum_mode"], str) and
                 item["minimum_mode"] in MODES, "contract_mode_invalid")
        _require(isinstance(item["effect"], str) and
                 item["effect"] in EFFECTS, "contract_effect_invalid")
        _require(isinstance(item["readiness"], str) and
                 item["readiness"] in READINESS, "contract_readiness_invalid")
        _require(APPROVED_CHECK_READINESS.get(identifier) == item["readiness"],
                 "contract_check_readiness_unapproved")
        _require(isinstance(item["depends_on"], list) and
                 all(isinstance(dep, str) and dep for dep in item["depends_on"]),
                 "contract_dependencies_invalid")
        _require(len(item["depends_on"]) == len(set(item["depends_on"])),
                 "contract_duplicate_dependency")
        if item["minimum_mode"] in ("quick", "diagnose"):
            _require(item["effect"] == "read_only",
                     "contract_readonly_mode_violation")
        by_id[identifier] = item

    # Contract PASS is valid only for the complete reviewed 19-check baseline.
    _require(set(by_id) == set(APPROVED_REPORT_TEXT),
             "contract_incomplete_check_inventory")

    checked: set[str] = set()
    active: set[str] = set()

    def visit(identifier: str) -> None:
        _require(identifier in by_id, "contract_unknown_dependency")
        _require(identifier not in active, "contract_dependency_cycle")
        if identifier in checked:
            return
        active.add(identifier)
        item = by_id[identifier]
        for dependency in item["depends_on"]:
            _require(dependency != identifier, "contract_self_dependency")
            _require(dependency in by_id, "contract_unknown_dependency")
            _require(MODES.index(by_id[dependency]["minimum_mode"]) <=
                     MODES.index(item["minimum_mode"]),
                     "contract_dependency_mode_violation")
            visit(dependency)
        active.remove(identifier)
        checked.add(identifier)

    for identifier in by_id:
        visit(identifier)
    # First report intrinsic schema/DAG errors using their established codes.
    # Then reject otherwise-well-formed but semantically unauthorized metadata.
    for identifier, item in by_id.items():
        reviewed = APPROVED_CHECK_SEMANTICS.get(identifier)
        _require(isinstance(reviewed, dict),
                 "contract_check_semantics_unapproved")
        _require(item["error_code"] == reviewed["error_code"],
                 "contract_check_error_code_unapproved")
        _require(item["component"] == reviewed["component"],
                 "contract_check_component_unapproved")
        _require(
            item["minimum_mode"] == reviewed["minimum_mode"] and
            item["effect"] == reviewed["effect"] and
            item["depends_on"] == reviewed["depends_on"],
            "contract_check_execution_unapproved",
        )
    return len(checked)


def make_report_record(
    contract: dict[str, Any], check_id: str, status: str, *,
    evidence: dict[str, object] | None = None,
    error_code: str | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    """Construct a bounded record only from reviewed strings and allowlisted facts.

    There is deliberately no argument for raw exception text, dynamic summary,
    free-form remediation, URLs, file paths, SQL queries, or secret-bearing logs.
    Future report runners MUST use this boundary instead of serializing probes.
    """
    validate_contract(contract)
    checks = {item["id"]: item for item in contract["checks"]}
    _require(isinstance(check_id, str) and check_id in checks,
             "report_check_unknown")
    check = checks[check_id]
    _require(status in STATUSES, "report_status_invalid")
    _require(not (status == "PASS" and check["readiness"] == "planned"),
             "report_unimplemented_pass")
    # OFF-0 is contract-only: even an existing reusable component has no
    # bound OFF-1 probe execution, so no live per-check PASS is authorized.
    # A caller-supplied HTTP 200 or fabricated hash is not execution proof.
    # OFF-1 may grant success ONLY through a reviewed, check-specific probe
    # and a separately validated evidence path; changing JSON is insufficient.
    _require(status != "PASS", "report_pass_probe_not_implemented")
    # A planned check has no probe and therefore cannot have executed or failed.
    # It must not be presented as PASS, FAIL or WARN in offline acceptance.
    if check["readiness"] == "planned":
        _require(status == "SKIP" and error_code == "check_not_implemented",
                 "report_unimplemented_check")
    _require(type(duration_ms) is int and 0 <= duration_ms <= 86_400_000,
             "report_duration_invalid")
    # OFF-0 never executes a probe. A nonzero duration would invent an
    # execution time even for the only permitted no-probe SKIP outcome.
    _require(duration_ms == 0, "report_skip_duration_unverified")
    if status == "FAIL":
        _require(error_code is not None, "report_failure_code_missing")
        _require(error_code == check["error_code"], "report_error_code_unsafe")
    elif status == "SKIP":
        _require(error_code is not None, "report_skip_code_missing")
        _require(isinstance(error_code, str) and error_code in SKIP_REASON_CODES,
                 "report_error_code_unsafe")
        # OFF-0 has no checked dependencies, runtime authentication state,
        # or selected-mode execution trace. All operational SKIP explanations
        # beyond "probe not implemented" would be speculative. OFF-1 must
        # introduce reviewed reason-specific provenance before enabling them.
        _require(error_code == "check_not_implemented",
                 "report_skip_reason_unverified")
    elif status == "PASS":
        _require(error_code is None, "report_pass_with_error")
    else:  # WARN: soft check-specific warning or general warning without a code.
        _require(error_code is None or error_code == check["error_code"],
                 "report_error_code_unsafe")
    values = evidence if evidence is not None else {}
    _require(isinstance(values, dict) and
             len(values) <= contract["report_policy"]["max_evidence_entries"],
             "report_evidence_invalid")
    policy = contract["report_policy"]["permitted_evidence"]
    safe: dict[str, object] = {}
    for key, value in values.items():
        _require(isinstance(key, str) and key in policy,
                 "report_evidence_key_unsafe")
        kind = policy[key]
        if kind == "nonnegative_integer":
            ok = type(value) is int and 0 <= value <= 10**12
        elif kind == "http_status":
            ok = type(value) is int and 100 <= value <= 599
        elif kind == "boolean":
            ok = type(value) is bool
        elif kind == "sha256":
            ok = (isinstance(value, str) and
                  re.fullmatch(r"[0-9a-f]{64}", value) is not None)
        elif kind == "classification":
            ok = value in ("FULL_LIVE", "HYBRID", "OFFLINE")
        else:
            ok = False
        _require(ok and
                 (not isinstance(value, str) or
                  len(value) <= contract["report_policy"]["max_evidence_value_chars"]),
                 "report_evidence_value_unsafe")
        safe[key] = value
    # OFF-0 has no trusted execution-bound probe. A FAIL or WARN would claim
    # an operational check ran, just as a proofless PASS would. Keep those
    # outcomes disabled until OFF-1 binds them to reviewed live probes.
    _require(status not in ("FAIL", "WARN"),
             "report_outcome_probe_not_implemented")
    # OFF-0 SKIP is a declaration of non-execution, never observational data.
    # Even structurally valid status/hash/classification values would be
    # fabricated here because this contract-only stage has no actual probe.
    _require(not safe, "report_skip_evidence_untrusted")
    return {
        "check_id": check_id,
        "component": check["component"],
        "status": status,
        "severity": ("error" if status == "FAIL" else
                     "warning" if status == "WARN" else "info"),
        "error_code": error_code,
        "summary": check["title"],
        "evidence": safe,
        # No operational failure was observed in OFF-0. Displaying the
        # check's failure remediation here would be a false diagnosis.
        "remediation": None,
        "dependency": list(check["depends_on"]),
        "duration_ms": duration_ms,
    }




def _json_exceeds_nesting_limit(content: str, limit: int = 128) -> bool:
    """Scan structural braces outside strings, independently of JSON parser depth.

    Malformed JSON is still rejected by json.loads; this bound simply prevents
    deeply nested (even valid) JSON from being accepted differently by Python
    versions or causing interpreter recursion errors.
    """
    depth = 0
    inside_string = False
    escaped = False
    for char in content:
        if inside_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                inside_string = False
            continue
        if char == '"':
            inside_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return True
        elif char in "]}":
            depth -= 1
            if depth < 0:
                return False  # Invalid structure goes to json.loads.
    return False

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path,
        default=Path(__file__).resolve().parents[1] /
                "docs/operations/sraf_airgap_off0_checks.v1.json",
    )
    args = parser.parse_args()
    # No unbounded read: reject special devices and read at most limit + 1 bytes.
    limit = 256 * 1024
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(args.registry, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                print("OFF0_CONTRACT = FAIL (contract_file_not_regular)")
                return 2
            parts = []
            total = 0
            while total <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - total))
                if not chunk:
                    break
                parts.append(chunk)
                total += len(chunk)
            if total > limit:
                print("OFF0_CONTRACT = FAIL (contract_file_too_large)")
                return 2
            content = b"".join(parts).decode("utf-8")
        finally:
            os.close(fd)
    except (OSError, UnicodeError):
        print("OFF0_CONTRACT = FAIL (contract_file_unreadable)")
        return 2
    if _json_exceeds_nesting_limit(content):
        print("OFF0_CONTRACT = FAIL (contract_json_invalid)")
        return 2
    try:
        value = json.loads(content)
    except (ValueError, RecursionError):
        # Includes JSONDecodeError and Python 3.11's oversized integer limit.
        # Do not catch ContractError here: it is reported separately below.
        print("OFF0_CONTRACT = FAIL (contract_json_invalid)")
        return 2
    try:
        count = validate_contract(value)
    except ContractError as exc:
        print(f"OFF0_CONTRACT = FAIL ({exc})")
        return 1
    print(f"OFF0_CONTRACT = PASS (checks={count}, schema-only; no runtime probes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
