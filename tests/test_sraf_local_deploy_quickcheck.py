"""SRAF one-command local deployment quickcheck synthetic nonlive regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sraf_local_deploy_quickcheck as target


@pytest.fixture
def probes(tmp_path, monkeypatch):
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(target.platform_probe, "observe", lambda: {
        "status": "PASS_PARTIAL", "odbc18": "REGISTERED_CONFIG_ONLY",
        "odbc_binary_header": "ELF64_ARCH_MATCH_HEADER_ONLY",
    })
    monkeypatch.setattr(target.deps_probe, "observe", lambda root: {
        "status": "PASS_PARTIAL", "requirements_checked": 15,
        "installed_direct_count": 15, "scheme_installed_direct_count": 13,
        "user_site_fallback_direct_count": 2, "unlocked_direct_count": 15,
    })
    monkeypatch.setattr(target.launch_probe, "observe", lambda: {
        "status": "PASS_PARTIAL",
        "path_python_identity": "MATCH",
        "uvicorn_shebang_identity": "DIRECT_MATCH",
        "selected_python_user_site_active": True,
    })
    monkeypatch.setattr(target.host_probe, "probe_disk", lambda:
                        SimpleNamespace(status="PASS"))
    monkeypatch.setattr(target.worker_probe, "probe_worker_process_identities",
                        lambda root: SimpleNamespace(
                            status="PASS",
                            reason="worker_process_identities_verified",
                            evidence={"verified_role_count": 2}))
    monkeypatch.setattr(target.listener_probe, "_pin_root_directory",
                        lambda root: os.open(root, os.O_RDONLY))
    monkeypatch.setattr(target.listener_probe, "_identity",
                        lambda fd, port: (1234, "45678"))
    monkeypatch.setattr(target.listener_probe, "_same_process",
                        lambda pid, start, stat, port: True)
    monkeypatch.setattr(target.listener_probe, "_listener_inode",
                        lambda port: "123456")
    monkeypatch.setattr(target.listener_probe, "_owns_socket",
                        lambda pid, inode: True)
    monkeypatch.setattr(target.listener_probe, "_procfs_unfiltered",
                        lambda: True)
    # Full strict listener scan must never be invoked by this quickcheck.
    monkeypatch.setattr(target.listener_probe, "_exclusive_socket_owner",
                        lambda *a: pytest.fail("unrequested global FD scan"))
    monkeypatch.setattr(target.listener_probe, "attest_api_listener",
                        lambda *a: pytest.fail("unrequested strict attestation"))
    return tmp_path


def test_one_command_aggregates_six_real_probe_contracts(probes):
    result = target.observe(probes)
    assert result["schema"] == target.SCHEMA
    assert result["mode"] == "LOCAL_PASSIVE_NO_NETWORK_NO_ARTIFACTS"
    assert result["status"] == "PASS_PARTIAL"
    assert result["required_passive_checks"] == 6
    assert result["passive_checks_observed"] == 6
    rows = {x["id"]: x for x in result["checks"]}
    assert set(rows) == set(target._CHECK_NAMES)
    assert rows["direct_distribution_metadata"]["metadata_observed"] == 15
    assert rows["direct_distribution_metadata"]["active_user_site_fallback_observed"] == 2
    assert rows["direct_distribution_metadata"]["unlocked_direct_count"] == 15
    assert rows["static_launchers"]["path_python_identity"] == "MATCH"
    assert rows["worker_process_identity"]["verified_role_count"] == 2
    assert rows["api_listener_preflight"]["prerequisites_observed"] == 6
    assert rows["api_listener_preflight"]["strict_listener_exclusive_socket_owner"] == "NOT_TESTED"
    assert rows["api_listener_preflight"]["strict_api_listener_attested"] is False
    assert result["production_release_ready"] is False
    assert result["network_requests_performed"] is False
    assert result["evidence_file_written"] is False
    assert result["full_live_acceptance"] == "NOT_TESTED"
    assert result["trusted_offline_wheelhouse"] == "NOT_TESTED"


def test_prints_human_summary_and_one_shareable_redacted_json(probes, capsys, monkeypatch):
    monkeypatch.chdir(probes)
    assert target.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "SRAF LOCAL DEPLOY QUICKCHECK" in lines[0]
    assert any("worker_process_identity=PASS_PARTIAL" in x for x in lines)
    assert any("api_listener_preflight=PASS_PARTIAL" in x for x in lines)
    assert lines[-2] == "RESULT=PASS_PARTIAL production_release_ready=false"
    assert lines[-1].startswith("SRAF_DEPLOY_CHECK_JSON=")
    parsed = json.loads(lines[-1].split("=", 1)[1])
    assert parsed["schema"] == target.SCHEMA
    assert str(probes) not in "\n".join(lines)
    assert '"pid":' not in lines[-1]
    assert "PASSWORD" not in lines[-1]


def test_failed_component_isolated_and_errors_are_redacted(probes, monkeypatch):
    def broken(root):
        raise RuntimeError("private-password SECRET /private/host 9999")
    monkeypatch.setattr(target.worker_probe, "probe_worker_process_identities", broken)
    output = target.observe(probes)
    rows = {r["id"]: r for r in output["checks"]}
    assert output["status"] == "INCOMPLETE"
    assert output["passive_checks_observed"] == 5
    assert rows["worker_process_identity"]["status"] == "INCOMPLETE"
    assert rows["worker_process_identity"]["reason"] == "passive_probe_unverifiable"
    assert rows["api_listener_preflight"]["status"] == "PASS_PARTIAL"
    assert "SECRET" not in json.dumps(output)
    assert "/private/host" not in json.dumps(output)


def test_no_root_match_stops_before_any_probe(probes, tmp_path, monkeypatch):
    monkeypatch.setattr(target.platform_probe, "observe",
                        lambda: pytest.fail("must not probe wrong root"))
    new = tmp_path / "unrelated"
    new.mkdir()
    out = target.observe(new)
    assert out["status"] == "INCOMPLETE"
    assert out["passive_checks_observed"] == 0
    assert all(x["reason"] == "repository_root_unverified" for x in out["checks"])


def test_unlocked_direct_requirements_do_not_claim_reproducible_wheelhouse(probes):
    out = target.observe(probes)
    row = {r["id"]: r for r in out["checks"]}["direct_distribution_metadata"]
    assert row["unlocked_direct_count"] == 15
    assert row["transitive_closure"] == "NOT_TESTED"
    assert row["wheelhouse_compatibility"] == "NOT_TESTED"
    assert out["production_release_ready"] is False


@pytest.mark.parametrize("field,value", [
    ("installed_direct_count", 16),
    ("requirements_checked", -1),
    ("scheme_installed_direct_count", 14),
    ("user_site_fallback_direct_count", "2"),
    ("unlocked_direct_count", 900),
])
def test_inconsistent_distribution_counts_fail_closed(probes, monkeypatch, field, value):
    details = {
        "status": "PASS_PARTIAL",
        "requirements_checked": 15, "installed_direct_count": 15,
        "scheme_installed_direct_count": 13,
        "user_site_fallback_direct_count": 2,
        "unlocked_direct_count": 15,
    }
    details[field] = value
    monkeypatch.setattr(target.deps_probe, "observe", lambda root: details)
    out = target.observe(probes)
    row = {x["id"]: x for x in out["checks"]}["direct_distribution_metadata"]
    assert row["status"] == "INCOMPLETE"
    assert out["status"] == "INCOMPLETE"


def test_first_api_prerequisite_failure_is_named_without_any_pid(probes, monkeypatch):
    monkeypatch.setattr(target.listener_probe, "_listener_inode",
                        lambda port: None)
    out = target.observe(probes)
    row = {x["id"]: x for x in out["checks"]}["api_listener_preflight"]
    assert out["status"] == "INCOMPLETE"
    assert row["prerequisites_observed"] == 3
    assert row["first_unverified_gate"] == "tcp_listener_unique"
    assert row["strict_listener_exclusive_socket_owner"] == "NOT_TESTED"
    assert "1234" not in json.dumps(out)
    assert "45678" not in json.dumps(out)


def test_worker_pass_without_both_roles_must_fail_closed(probes, monkeypatch):
    monkeypatch.setattr(target.worker_probe, "probe_worker_process_identities",
                        lambda root: SimpleNamespace(
                            status="PASS",
                            reason="worker_process_identities_verified",
                            evidence={"verified_role_count": 1}))
    out = target.observe(probes)
    row = {x["id"]: x for x in out["checks"]}["worker_process_identity"]
    assert row["status"] == "INCOMPLETE"


def test_disk_low_is_not_reported_as_green(probes, monkeypatch):
    monkeypatch.setattr(target.host_probe, "probe_disk",
                        lambda: SimpleNamespace(status="WARN"))
    out = target.observe(probes)
    assert out["status"] == "INCOMPLETE"
    assert any(x["id"] == "host_disk" and x["status"] == "WARN"
               for x in out["checks"])


def test_bad_cli_args_never_start_a_probe(probes, monkeypatch):
    monkeypatch.setattr(target.platform_probe, "observe",
                        lambda: pytest.fail("unapproved mode executed"))
    with pytest.raises(SystemExit) as caught:
        target.main(["--live-report"])
    assert caught.value.code == 2


def test_operator_quickcheck_does_not_depend_on_evidence_directory(probes, monkeypatch):
    # The existing OFF-1 hub output path can fail due shared-mount ownership.
    # This one-command local check deliberately never calls its output guard.
    from tools import sraf_airgap_report_jobs_acceptance as reports
    monkeypatch.setattr(reports, "_secure_output_dir",
                        lambda p: pytest.fail("quickcheck must not write"))
    result = target.observe(probes)
    assert result["status"] == "PASS_PARTIAL"
    assert result["evidence_file_written"] is False
