"""Single-direction incremental deployment artifact: no Git on Linux."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from scripts import build_sraf_event_time_readonly_bundle as bundle


def _unpack(tmp_path: Path):
    archive = tmp_path / "sraf-date-readonly.zip"
    manifest = bundle.build(bundle.ROOT, archive, source_head="a" * 40)
    with ZipFile(archive) as zipped:
        names = zipped.namelist()
        assert len(names) == len(set(names))
        assert all(
            name.startswith("_sraf_date_readonly/")
            and "../" not in name and "/.env" not in name
            and "http_ca.crt" not in name
            and ".git/" not in name and "password" not in name.lower()
            for name in names
        )
        zipped.extractall(tmp_path)
    return tmp_path / bundle.BUNDLE_DIR, manifest


def test_allowlisted_zip_never_contains_active_runtime_or_private_configuration(tmp_path):
    extracted, manifest = _unpack(tmp_path)
    assert manifest["source_head"] == "a" * 40
    assert manifest["no_git_required_on_linux"] is True
    assert manifest["active_runtime_overwrite"] is False
    assert not (extracted / ".env.local").exists()
    assert not (extracted / "run_sra_api.sh").exists()
    assert not (extracted / ".git").exists()
    report = json.loads((extracted / "manifest.json").read_text())
    assert report["file_count"] == len(bundle.FILES) + 2
    assert len(report["files_sha256"]) == report["file_count"]
    for filename, digest in report["files_sha256"].items():
        assert hashlib.sha256((extracted / filename).read_bytes()).hexdigest() == digest


def test_portable_sidecar_default_no_network_without_linux_git(tmp_path):
    extracted, _ = _unpack(tmp_path)
    run = subprocess.run(
        [sys.executable, str(extracted / "tools/sraf_event_time_readonly_acceptance.py"),
         "--no-network"],
        cwd=extracted, capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 2
    data = json.loads(run.stdout)
    assert data["status"] == "NOT_TESTED"
    assert "git" not in data
    assert run.stderr == ""


def test_minimal_bundle_imports_real_new_date_contract_and_tls_modules(tmp_path):
    extracted, _ = _unpack(tmp_path)
    code = (
        "from agent.es.event_time import parse_structured_time;"
        "from agent.es.query_body import _structured_date_filter;"
        "from tools.sraf_airgap_off1b_es_https_mapping import _https_get;"
        "from tools.sraf_event_time_readonly_acceptance import _strict_live_observe;"
        "assert parse_structured_time('2025-06-17','day','Event').start=='2025-06-17';"
        "assert isinstance(_structured_date_filter('2025-06-17','2025-06-17'),dict)"
    )
    run = subprocess.run(
        [sys.executable, "-c", code],
        cwd=extracted, capture_output=True, text=True, timeout=20,
    )
    assert run.returncode == 0, run.stderr[-1400:]
    assert run.stdout == ""


def test_zip_contains_single_runner_and_does_not_touch_deployed_repo(tmp_path):
    extracted, _ = _unpack(tmp_path)
    runner = (extracted / "run.sh").read_text()
    assert "SRAF_CONFIG_ROOT" in runner
    assert 'exec "$PYTHON_BIN"' in runner
    for forbidden in ("git fetch", "git worktree", "git pull", "git checkout",
                      "rm -rf", "sudo", "systemctl", "run_sra_api.sh"):
        assert forbidden not in runner
    assert "poc-agent" in runner


@pytest.mark.parametrize("head", ["not-a-hash", "A" * 40, "123"])
def test_builder_rejects_invalid_explicit_source_head(head, tmp_path):
    with pytest.raises(SystemExit):
        bundle.main(["--output", str(tmp_path / "artifact.zip"),
                     "--source-head", head])
