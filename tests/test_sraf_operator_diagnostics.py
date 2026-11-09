"""Nonlive regression gates for SRAF layered operator diagnostics."""
from __future__ import annotations

from argparse import Namespace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools import sraf_operator_diagnostics as target


ROOT = Path(__file__).resolve().parents[1]


def args(level="L1", **overrides):
    values = {
        "level": level, "probe_sql_read": False,
        "probe_es_tls_mapping": False, "probe_llm_inference": False,
        "ollama_server_pid": None, "live_report": False,
        "token_env": None, "output_dir": None, "max_seconds": 1200,
        "full_e2e": False, "verification": "release",
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.fixture
def probes(monkeypatch):
    def local(launcher_port=None):
        return "PASS_PARTIAL", [
            target._row("L0." + name, "PASS_PARTIAL", "local_observed")
            for name in target.L0_CHECKS
        ]
    def l1():
        return {"safe": "config"}, [
            target._row("L1." + name, "PASS", "observed")
            for name in target.L1_CHECKS
        ]
    monkeypatch.setattr(target, "_local_rows", local)
    monkeypatch.setattr(target, "_l1_rows", l1)
    return monkeypatch


def forbidden(*a, **kw):
    raise AssertionError("unselected intrusive probe executed")


def test_default_l1_never_sql_es_llm_or_report_job(probes):
    for name in ("_sql_status", "_es_status", "_llm_status", "_live_status", "_full_e2e_status"):
        probes.setattr(target, name, forbidden)
    result = target.run(args())
    assert result["status"] == "PASS_PARTIAL"
    assert result["level"] == "L1"
    assert result["production_release_ready"] is False
    assert result["full_requirement_schedule_handoff_e2e"] == "NOT_TESTED"
    assert len(result["checks"]) == 6 + 4 + 3 + 1 + 1
    assert all(row["status"] == "NOT_TESTED" for row in result["checks"]
               if row["id"].startswith(("L2.", "L3.")))


def test_l2_requires_explicit_component_selection(probes):
    result = target.run(args("L2"))
    assert result["status"] == "INCOMPLETE"
    assert result["l2_selected"] == []


def test_l2_sql_only_does_not_run_other_optins(probes):
    probes.setattr(target, "_sql_status",
                   lambda: ("PASS", "sql_constant_select_observed"))
    for name in ("_es_status", "_llm_status", "_live_status"):
        probes.setattr(target, name, forbidden)
    result = target.run(args("L2", probe_sql_read=True))
    assert result["status"] == "PASS_PARTIAL"
    assert result["l2_selected"] == ["sql_constant_read"]
    assert next(r for r in result["checks"]
                if r["id"] == "L2.sql_constant_read")["status"] == "PASS"


def test_l2_es_with_missing_tcp_must_not_send_credentials(probes):
    def l1():
        return {}, [target._row("L1." + name,
                                "SKIP" if name == "es_tcp" else "PASS",
                                "observed") for name in target.L1_CHECKS]
    probes.setattr(target, "_l1_rows", l1)
    probes.setattr(target, "_es_status", forbidden)
    result = target.run(args("L2", probe_es_tls_mapping=True))
    assert next(r for r in result["checks"] if r["id"] == "L2.es_tls_mapping") == \
        target._row("L2.es_tls_mapping", "SKIP", "upstream_not_verified")
    assert result["status"] == "INCOMPLETE"


def test_l2_explicit_llm_only_with_pid_reaches_reviewed_helper(probes):
    called = []
    probes.setattr(target, "_llm_status",
                   lambda cfg, pid: (called.append((cfg, pid)) or
                                     ("PASS", "llm_inference_generation_observed")))
    result = target.run(args("L2", probe_llm_inference=True, ollama_server_pid=432))
    assert called == [({"safe": "config"}, 432)]
    assert result["status"] == "PASS_PARTIAL"
    assert result["full_requirement_schedule_handoff_e2e"] == "NOT_TESTED"


def test_l3_missing_api_health_never_submits(probes):
    def l1():
        return {}, [target._row("L1." + name,
                                "FAIL" if name == "api_health" else "PASS",
                                "observed") for name in target.L1_CHECKS]
    probes.setattr(target, "_l1_rows", l1)
    probes.setattr(target, "_live_status", forbidden)
    result = target.run(args("L3", live_report=True, token_env="SRAF_TEST_BEARER",
                             output_dir="/tmp/private"))
    assert next(r for r in result["checks"] if r["id"] == "L3.report_job_docx")["status"] == "SKIP"
    assert result["status"] == "FAIL"


def test_l3_success_still_does_not_claim_schedule_e2e(probes):
    probes.setattr(target, "_live_status",
                   lambda a, original_port: ("PASS_PARTIAL", "one_report_job_docx_observed_only"))
    result = target.run(args("L3", live_report=True, token_env="SRAF_TEST_BEARER",
                             output_dir="/private"))
    assert result["status"] == "PASS_PARTIAL"
    assert result["full_requirement_schedule_handoff_e2e"] == "NOT_TESTED"
    assert next(r for r in result["checks"]
                if r["id"] == "L3.requirement_schedule_handoff_e2e")["status"] == "NOT_TESTED"


@pytest.mark.parametrize("argv", [
    ["--level", "L1", "--probe-sql-read"],
    ["--level", "L2", "--live-report", "--token-env", "ABC"],
    ["--level", "L2", "--probe-llm-inference"],
    ["--level", "L2", "--ollama-server-pid", "1000"],
    ["--level", "L3"],
    ["--level", "L3", "--live-report", "--token-env", "BAD-NAME", "--output-dir", "/tmp/x"],
    ["--level", "L3", "--live-report", "--token-env", "GOOD", "--output-dir", "relative"],
    ["--level", "L3", "--live-report", "--token-env", "GOOD", "--output-dir", "/tmp/x", "--probe-sql-read"],
    ["--level", "L1", "--max-seconds", "99999"],
    ["--level", "L1", "--full-e2e", "--output-dir", "/private"],
    ["--level", "L3", "--full-e2e", "--output-dir", "relative"],
    ["--level", "L3", "--full-e2e", "--live-report", "--output-dir", "/private"],
    ["--level", "L3", "--full-e2e", "--token-env", "SRAF_TEST_BEARER", "--output-dir", "/private"],
    ["--level", "L1", "--verification", "functional"],
])
def test_invalid_authorization_fails_before_probes(monkeypatch, argv):
    monkeypatch.setattr(target, "run", forbidden)
    with pytest.raises(SystemExit) as ex:
        target.main(argv)
    assert ex.value.code == 2


def test_tcp_and_http_observations_require_real_consistent_evidence():
    assert target._tcp_status({"configuration": "RESOLVED", "tcp_probe": "PASS",
                               "host_scope": "LOOPBACK_IPV4",
                               "reason": "configured_tcp_connected"}) == (
                                   "PASS", "configured_tcp_connected")
    assert target._tcp_status({"configuration": "INVALID", "tcp_probe": "PASS",
                               "host_scope": "LOOPBACK_IPV4",
                               "reason": "configured_tcp_connected"})[0] == "FAIL"
    assert target._health_status({"http_probe": "PASS", "http_status": 500,
                                  "reason": "healthz_http_200",
                                  "healthz_endpoint": "/healthz",
                                  "http_method": "GET"})[0] != "PASS"


def test_main_json_is_fixed_and_redacted(monkeypatch, probes, capsys):
    monkeypatch.setattr(target, "_sql_status", forbidden)
    assert target.main([]) == 0
    output = capsys.readouterr().out.splitlines()
    assert output[-1].startswith("SRAF_DIAGNOSTICS_JSON=")
    doc = json.loads(output[-1].split("=", 1)[1])
    assert doc["status"] == "PASS_PARTIAL"
    assert "private/password" not in str(doc)


def test_root_launcher_help_has_no_probes():
    wrapper = ROOT / "1_完整診斷驗收_SRAF.sh"
    assert wrapper.is_file()
    script = wrapper.read_text(encoding="utf-8")
    assert 'exec "$PYTHON_BIN"' in script
    assert "eval " not in script
    env = dict(os.environ, SRAF_PYTHON=sys.executable)
    done = subprocess.run(["bash", str(wrapper), "--help"], cwd=ROOT,
                          env=env, capture_output=True, text=True, timeout=12)
    assert done.returncode == 0, done.stderr
    assert "--level" in done.stdout


def test_l1_missing_import_is_not_a_fake_skip(probes):
    def broken():
        raise ModuleNotFoundError("missing optional deployment dependency")
    probes.setattr(target, "_l1_rows", broken)
    result = target.run(args())
    assert result["status"] == "INCOMPLETE"
    assert all(row["reason"] == "l1_dependency_import_unavailable"
               for row in result["checks"] if row["id"].startswith("L1."))


def test_l3_passes_original_launcher_port_even_after_dotenv(probes):
    probes.setenv("PORT", "9005")
    def loaded_env():
        os.environ["PORT"] = "12345"
        return {}, [target._row("L1." + name, "PASS", "observed")
                    for name in target.L1_CHECKS]
    probes.setattr(target, "_l1_rows", loaded_env)
    observed = []
    probes.setattr(target, "_live_status",
                   lambda selection, launcher_port:
                   (observed.append(launcher_port) or
                    ("PASS_PARTIAL", "one_report_job_docx_observed_only")))
    target.run(args("L3", live_report=True, token_env="SRAF_TEST_BEARER",
                    output_dir="/private"))
    assert observed == ["9005"]


def test_l3_child_job_sees_original_unset_port_and_restores_env(monkeypatch):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    monkeypatch.setenv("SRAF_TEST_BEARER", "do-not-print")
    monkeypatch.setenv("PORT", "12345")  # simulates dotenv loaded by L1
    def fake_job(argv):
        assert "PORT" not in os.environ
        assert argv[argv.index("--token-env") + 1] == "SRAF_TEST_BEARER"
        print("SRAF_REPORT_JOBS_ACCEPTANCE=PASS_PARTIAL")
        print("EVIDENCE_FILE=/secret/private/location")
        return 0
    monkeypatch.setattr(jobs, "main", fake_job)
    status, reason = target._live_status(
        args("L3", token_env="SRAF_TEST_BEARER", output_dir="/private"), None)
    assert (status, reason) == ("PASS_PARTIAL", "one_report_job_docx_observed_only")
    assert os.environ["PORT"] == "12345"


def test_disk_warning_preserves_each_original_l0_observation(monkeypatch):
    from tools import sraf_local_deploy_quickcheck as quick
    rows = [dict(id=name, status="PASS_PARTIAL", reason="sample_observed")
            for name in target.L0_CHECKS]
    rows[3] = dict(id="host_disk", status="WARN", reason="disk_space_low")
    seen_ports = []
    def observe(root, *, api_port=9002):
        seen_ports.append(api_port)
        return {"schema": quick.SCHEMA, "status": "INCOMPLETE", "checks": rows}
    monkeypatch.setattr(quick, "observe", observe)
    overall, results = target._local_rows("9005")
    assert overall == "INCOMPLETE"
    assert seen_ports == [9005]
    assert [r["status"] for r in results].count("WARN") == 1
    assert len(results) == 6
    assert results[3]["reason"] == "disk_space_low"
    assert results[0]["status"] == "PASS_PARTIAL"


def test_invalid_launcher_port_does_not_perform_untrusted_preflight(monkeypatch):
    from tools import sraf_local_deploy_quickcheck as quick
    ports = []
    def observe(root, *, api_port=9002):
        ports.append(api_port)
        return {"schema": quick.SCHEMA, "status": "INCOMPLETE",
                "checks": [dict(id=name,
                                status="INCOMPLETE" if name == "api_listener_preflight" else "PASS_PARTIAL",
                                reason="api_listener_prerequisite_unverified" if name == "api_listener_preflight"
                                       else "sample_observed") for name in target.L0_CHECKS]}
    monkeypatch.setattr(quick, "observe", observe)
    status, observations = target._local_rows("INVALID_PORT")
    assert ports == [0]
    assert status == "INCOMPLETE"
    assert observations[-1]["status"] == "INCOMPLETE"


def test_l3_real_full_e2e_only_with_explicit_optin(probes):
    seen = []
    probes.setattr(target, "_live_status", forbidden)
    probes.setattr(target, "_full_e2e_status",
                   lambda selection: (seen.append(selection.verification) or
                                      ("PASS_PARTIAL", "live_requirement_chain_observed_not_airgap")))
    result = target.run(args("L3", full_e2e=True, verification="release",
                             output_dir="/private"))
    assert seen == ["release"]
    assert result["status"] == "PASS_PARTIAL"
    assert result["full_requirement_schedule_handoff_e2e"] == "OBSERVED_PARTIAL"
    assert result["l3_full_e2e_requested"] is True
    assert result["production_release_ready"] is False
    assert next(r for r in result["checks"]
                if r["id"] == "L3.report_job_docx")["status"] == "NOT_TESTED"


def test_l3_real_e2e_unavailable_upstream_never_mutates(probes):
    def l1():
        return {}, [target._row("L1." + name,
                                "SKIP" if name == "llm_tcp" else "PASS",
                                "observed") for name in target.L1_CHECKS]
    probes.setattr(target, "_l1_rows", l1)
    probes.setattr(target, "_full_e2e_status", forbidden)
    result = target.run(args("L3", full_e2e=True, output_dir="/private"))
    assert result["status"] == "INCOMPLETE"
    assert result["full_requirement_schedule_handoff_e2e"] == "INCOMPLETE_OR_FAILED"


def test_full_e2e_harness_trusted_private_env_live_only_and_no_stdout_leak(
        monkeypatch, tmp_path):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    from operator_e2e import test_requirement_schedule_e2e as harness
    operator = tmp_path / "operator_e2e"
    operator.mkdir()
    env = operator / "e2e.env.local"
    env.write_text("SRA_E2E_BASE_URL=http://127.0.0.1:9002\n", encoding="utf-8")
    env.chmod(0o600)
    monkeypatch.setattr(target, "ROOT", tmp_path)
    monkeypatch.setattr(jobs, "_secure_output_dir",
                        lambda path: os.open(tmp_path, os.O_RDONLY))
    observed = []
    def synthetic_harness(argv):
        observed.append(argv)
        assert argv[argv.index("--external-mode") + 1] == "live"
        assert argv[argv.index("--verification") + 1] == "release"
        print("SECRET PATH AND TOKEN MUST NOT BE FORWARDED")
        print("REQUIREMENT_E2E = PASS")
        print("FUNCTIONAL_RESULT = PASS")
        print("SOURCE_ATTESTATION = VERIFIED")
        print("DEPLOYMENT_ACCEPTANCE = ESTABLISHED")
        return 0
    monkeypatch.setattr(harness, "main", synthetic_harness)
    status, reason = target._full_e2e_status(
        args("L3", full_e2e=True, output_dir="/private"))
    assert (status, reason) == ("PASS_PARTIAL", "live_requirement_chain_observed_not_airgap")
    assert len(observed) == 1


def test_full_e2e_functional_not_reported_as_release(monkeypatch, tmp_path):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    from operator_e2e import test_requirement_schedule_e2e as harness
    (tmp_path / "operator_e2e").mkdir()
    env = tmp_path / "operator_e2e" / "e2e.env.local"
    env.write_text("private=1\n", encoding="utf-8")
    env.chmod(0o600)
    monkeypatch.setattr(target, "ROOT", tmp_path)
    monkeypatch.setattr(jobs, "_secure_output_dir",
                        lambda path: os.open(tmp_path, os.O_RDONLY))
    def synthetic_harness(argv):
        print("REQUIREMENT_E2E = PASS")
        print("FUNCTIONAL_RESULT = PASS")
        print("SOURCE_ATTESTATION = MISMATCH")
        print("DEPLOYMENT_ACCEPTANCE = NOT_ESTABLISHED")
        return 0
    monkeypatch.setattr(harness, "main", synthetic_harness)
    assert target._full_e2e_status(
        args("L3", full_e2e=True, verification="functional",
             output_dir="/private")) == (
             "PASS_PARTIAL", "functional_live_chain_observed_not_release")


def test_full_e2e_private_env_missing_does_not_call_harness(monkeypatch, tmp_path):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    from operator_e2e import test_requirement_schedule_e2e as harness
    monkeypatch.setattr(target, "ROOT", tmp_path)
    monkeypatch.setattr(jobs, "_secure_output_dir",
                        lambda path: os.open(tmp_path, os.O_RDONLY))
    monkeypatch.setattr(harness, "main", forbidden)
    assert target._full_e2e_status(
        args("L3", full_e2e=True, output_dir="/private")) == (
        "SKIP", "e2e_private_environment_unverified")


def test_full_e2e_private_env_group_readable_is_rejected(monkeypatch, tmp_path):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    from operator_e2e import test_requirement_schedule_e2e as harness
    (tmp_path / "operator_e2e").mkdir()
    env = tmp_path / "operator_e2e" / "e2e.env.local"
    env.write_text("private=1\n", encoding="utf-8")
    env.chmod(0o644)
    monkeypatch.setattr(target, "ROOT", tmp_path)
    monkeypatch.setattr(jobs, "_secure_output_dir",
                        lambda path: os.open(tmp_path, os.O_RDONLY))
    monkeypatch.setattr(harness, "main", forbidden)
    assert target._full_e2e_status(
        args("L3", full_e2e=True, output_dir="/private")) == (
        "SKIP", "e2e_private_environment_unverified")


def test_maintenance_report_distinguishes_worker_identity_from_service_outage():
    from tools.sraf_diagnostics_report import render_report
    rows = []
    for name in target.L0_CHECKS:
        rows.append(target._row("L0." + name,
                                "INCOMPLETE" if name == "worker_process_identity"
                                else "PASS" if name == "host_disk" else "PASS_PARTIAL",
                                "worker_process_identity_unverified"
                                if name == "worker_process_identity" else "sample_observed"))
    for name in target.L1_CHECKS:
        rows.append(target._row("L1." + name, "PASS",
                                "healthz_http_200" if name == "api_health"
                                else "configured_tcp_connected", 43))
    for name in target.L2_CHECKS:
        rows.append(target._row("L2." + name, "NOT_TESTED", "probe_not_requested"))
    rows.extend((target._row("L3.report_job_docx", "NOT_TESTED", "probe_not_requested"),
                 target._row("L3.requirement_schedule_handoff_e2e", "NOT_TESTED",
                             "probe_not_requested")))
    result = {"level": "L1", "status": "INCOMPLETE", "checks": rows}
    output = render_report(result)
    assert "API /healthz 已回傳 200" in output
    assert "Elasticsearch：TCP 連線可達" in output
    assert "LLM：TCP 連線可達" in output
    assert "0/2 不能解讀為兩個都掛掉" in output
    assert "尚未執行 SQL 功能測試" in output
    assert "尚未執行 Report Job" in output
    assert "綜合判定：待確認 (INCOMPLETE)" in output
    assert output.index("【二、需維護人員確認的項目") < output.index("【三、維護結論")


def test_human_report_does_not_infer_es_llm_functionality_from_tcp():
    from tools.sraf_diagnostics_report import render_report
    rows = [target._row(name, "PASS_PARTIAL", "test_observed")
            for name in ("L0." + n for n in target.L0_CHECKS)]
    rows.extend(target._row("L1." + n, "PASS", "configured_tcp_connected")
                for n in target.L1_CHECKS)
    rows.extend(target._row("L2." + n, "NOT_TESTED", "probe_not_requested")
                for n in target.L2_CHECKS)
    rows.append(target._row("L3.report_job_docx", "NOT_TESTED", "probe_not_requested"))
    rows.append(target._row("L3.requirement_schedule_handoff_e2e",
                            "NOT_TESTED", "probe_not_requested"))
    output = render_report({"level": "L1", "status": "PASS_PARTIAL", "checks": rows})
    assert "不驗證 TLS 憑證、身分、Mapping 或實際搜尋" in output
    assert "尚未測試" not in output or "功能驗收" in output
    assert "不能等同正式上線" in output


def test_human_report_never_uses_arbitrary_reason_or_sensitive_values():
    from tools.sraf_diagnostics_report import render_report
    rows = [target._row(name, "INCOMPLETE", "unknown_but_valid_reason")
            for name in ("L0." + n for n in target.L0_CHECKS)]
    rows.extend(target._row("L1." + n, "INCOMPLETE", "unknown_but_valid_reason")
                for n in target.L1_CHECKS)
    rows.extend(target._row("L2." + n, "NOT_TESTED", "probe_not_requested")
                for n in target.L2_CHECKS)
    rows.extend(target._row("L3.report_job_docx", "NOT_TESTED", "probe_not_requested")
                for _ in range(1))
    rows.append(target._row("L3.requirement_schedule_handoff_e2e",
                            "NOT_TESTED", "probe_not_requested"))
    output = render_report({"level": "L1", "status": "INCOMPLETE",
                            "checks": rows, "private": "SECRET_API_PASSWORD"})
    assert "unknown_but_valid_reason" not in output
    assert "SECRET_API_PASSWORD" not in output


def test_bad_report_contract_is_never_converted_to_success():
    from tools.sraf_diagnostics_report import render_report
    text = render_report({"level": "L1", "status": "PASS_PARTIAL",
                          "checks": [{"id": "L1.api_health", "status": "PASS"}]})
    assert "格式不完整" in text
    assert "綜合判定：正常" not in text


def test_relative_report_dir_refuses_before_any_probe(probes):
    probes.setattr(target, "run", forbidden)
    assert target.main(["--report-dir", "not/absolute"]) == 2


def test_optional_private_maintenance_report_written_as_both_formats(
        monkeypatch, probes, capsys, tmp_path):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    calls = []
    def private_dir(path):
        calls.append("guard")
        return os.open(tmp_path, os.O_RDONLY)
    def write(name, raw, fd):
        assert name.startswith("sraf-diagnostics-")
        assert name.endswith((".json", ".txt"))
        calls.append(name.rsplit(".", 1)[-1])
        assert b"SECRET_PASSWORD" not in raw
    monkeypatch.setattr(jobs, "_secure_output_dir", private_dir)
    monkeypatch.setattr(jobs, "_secure_write", write)
    code = target.main(["--report-dir", str(tmp_path)])
    printed = capsys.readouterr().out
    assert code == 0
    assert calls == ["guard", "txt", "json"]
    assert "REPORT_SAVE=PASS reason=private_txt_json_written" in printed
    assert "SRAF_DIAGNOSTICS_JSON=" in printed.splitlines()[-1]
    assert "【二、需維護人員確認的項目" in printed
    assert str(tmp_path) not in printed


def test_private_maintenance_report_invalid_trust_prevents_any_probes(
        monkeypatch, tmp_path, capsys):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    monkeypatch.setattr(jobs, "_secure_output_dir", forbidden)
    monkeypatch.setattr(target, "run", forbidden)
    assert target.main(["--report-dir", str(tmp_path)]) == 2
    assert "report_dir_unverified" in capsys.readouterr().out


def test_private_report_write_failure_returns_incomplete_without_exposing_path(
        monkeypatch, probes, capsys, tmp_path):
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    monkeypatch.setattr(jobs, "_secure_output_dir",
                        lambda path: os.open(tmp_path, os.O_RDONLY))
    monkeypatch.setattr(jobs, "_secure_write", forbidden)
    assert target.main(["--report-dir", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert "REPORT_SAVE=INCOMPLETE reason=report_write_unavailable" in output
    assert str(tmp_path) not in output


@pytest.mark.parametrize("state,reason", [
    ("FAIL", "healthz_http_unavailable"),
    ("SKIP", "api_tcp_not_verified"),
    ("INCOMPLETE", "healthz_unverified"),
])
def test_failed_or_skipped_api_health_description_never_claims_http_pass(
        state, reason):
    from tools.sraf_diagnostics_report import render_report
    rows = [target._row("L0." + n, "PASS_PARTIAL", "observed")
            for n in target.L0_CHECKS]
    for n in target.L1_CHECKS:
        if n == "api_health":
            rows.append(target._row("L1." + n, state, reason))
        else:
            rows.append(target._row("L1." + n, "PASS",
                                    "configured_tcp_connected"))
    rows.extend(target._row("L2." + n, "NOT_TESTED", "probe_not_requested")
                for n in target.L2_CHECKS)
    rows.extend((
        target._row("L3.report_job_docx", "NOT_TESTED", "probe_not_requested"),
        target._row("L3.requirement_schedule_handoff_e2e",
                    "NOT_TESTED", "probe_not_requested"),
    ))
    report = render_report({"level": "L1", "status": "INCOMPLETE", "checks": rows})
    api_line = next(line for line in report.splitlines()
                    if line.lstrip().startswith("[" + {
                        "FAIL": "失敗", "SKIP": "未完成", "INCOMPLETE": "待確認",
                    }[state] + "] API /healthz："))
    assert "通過" not in api_line
    assert "已收到" not in api_line
    assert "HTTP 檢查" in api_line
    assert "API 健康狀態尚未通過 HTTP 200 確認" in report


def test_raw_failure_cannot_become_success_by_fallback_description():
    from tools.sraf_diagnostics_report import render_report
    rows = [target._row("L0." + n, "FAIL", "unknown_but_safe_reason")
            for n in target.L0_CHECKS]
    rows.extend(target._row("L1." + n, "FAIL", "unknown_but_safe_reason")
                for n in target.L1_CHECKS)
    rows.extend(target._row("L2." + n, "NOT_TESTED", "probe_not_requested")
                for n in target.L2_CHECKS)
    rows.extend([
        target._row("L3.report_job_docx", "NOT_TESTED", "probe_not_requested"),
        target._row("L3.requirement_schedule_handoff_e2e",
                    "NOT_TESTED", "probe_not_requested"),
    ])
    text = render_report({"level": "L1", "status": "FAIL", "checks": rows})
    assert "[失敗] API /healthz：匿名 GET /healthz HTTP 檢查" in text
    assert "[失敗] Elasticsearch 連線：僅檢查 TCP 連線" in text
    assert "unknown_but_safe_reason" not in text
