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
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.fixture
def probes(monkeypatch):
    def local():
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
    for name in ("_sql_status", "_es_status", "_llm_status", "_live_status"):
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
                   lambda a: ("PASS_PARTIAL", "one_report_job_docx_observed_only"))
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
