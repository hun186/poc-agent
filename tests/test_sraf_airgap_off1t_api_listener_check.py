"""OFF-1T operator-only standalone API listener CLI contract and redaction."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import sraf_airgap_off1t_api_listener_check as cli
from tools import sraf_airgap_off1s_api_listener as listener


def test_positive_reuses_actual_off1s_probe(monkeypatch, tmp_path, capsys):
    root = tmp_path / "private-repository"
    root.mkdir()
    proof = listener.ListenerProof(1234, "10001", 9002, "56789")
    called = []
    def verified(path, port):
        called.append((path, port))
        return proof
    monkeypatch.setattr(listener, "attest_api_listener", verified)
    assert cli.main(["--project-root", str(root), "--api-port", "9002",
                     "--format", "json"]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result == {
        "schema": "sraf_airgap_off1t_api_listener_v1",
        "check_id": "API-LISTENER-01",
        "status": "PASS",
        "reason": "api_listener_attested",
        "mode": "PARTIAL_ONLY_NOT_ACCEPTANCE",
        "feature_acceptance": "NOT_TESTED",
        "listener_identity_observed": True,
        "network_requests": 0,
        "credentials_sent": False,
    }
    assert called == [(root, "9002")]
    assert not output.err
    assert str(root) not in output.out
    for forbidden in ("1234", "10001", "56789", "9002", "Bearer", "SECRET"):
        assert forbidden not in output.out


def test_missing_identity_is_skip_not_fake_pass(monkeypatch, tmp_path, capsys):
    root = tmp_path / "secret-path"
    root.mkdir()
    monkeypatch.setattr(listener, "attest_api_listener", lambda *args: None)
    assert cli.main(["--project-root", str(root), "--api-port", "9002"]) == 2
    output = capsys.readouterr()
    assert output.out.strip() == (
        "OFF1T_API_LISTENER=SKIP reason=api_listener_unverified "
        "mode=PARTIAL_ONLY_NOT_ACCEPTANCE feature_acceptance=NOT_TESTED")
    assert str(root) not in output.out and not output.err


@pytest.mark.parametrize("port", ["0", "65536", "abc", "9002x", "-1", ""])
def test_invalid_port_never_promotes_pass(tmp_path, port, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    assert cli.main(["--project-root", str(root), "--api-port", port,
                     "--format", "json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "SKIP"
    assert result["listener_identity_observed"] is False
    assert result["network_requests"] == 0


def test_relative_project_path_rejected(tmp_path):
    result = cli.observe(Path("relative-repo"), "9002")
    assert result["status"] == "SKIP"


def test_actual_cli_does_not_require_database_secrets_or_network(tmp_path):
    command = [sys.executable, str(cli.__file__), "--project-root",
               str(tmp_path), "--api-port", "9002", "--format", "json"]
    output = subprocess.run(command, capture_output=True, text=True,
                            check=False, timeout=15)
    assert output.returncode == 2
    assert output.stderr == ""
    assert json.loads(output.stdout)["feature_acceptance"] == "NOT_TESTED"


def test_no_api_credential_or_http_imports():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "from tools.sraf_airgap_off1s_api_listener import probe_api_listener" in source
    assert "probe_remote_report_job" not in source
    assert "_remote_status" not in source
    assert "requests." not in source
