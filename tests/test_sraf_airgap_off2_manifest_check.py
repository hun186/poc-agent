"""OFF-2 read-only listed-runtime provenance tests (no network, no SQL/LLM)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.sraf_airgap_off2_manifest_check import observe, MANIFEST


def _fixture(root: Path, *, name: str = "agent/probe.py",
             content: bytes = b"trusted runtime bytes\n") -> str:
    selected = root / name
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_bytes(content)
    manifest = {
        "schema_version": 2, "repository": "hun186/poc-agent",
        "reviewed_runtime_sha": "a" * 40,
        "runtime_files": [
            {"path": name, "sha256": hashlib.sha256(content).hexdigest()},
        ],
    }
    data = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    (root / MANIFEST).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_pinned_bytes_match_only_is_partial_not_release(tmp_path):
    pin = _fixture(tmp_path)
    assert observe(tmp_path, pin) == {
        "status": "PASS_PARTIAL", "reason": "listed_runtime_bytes_match_only",
        "files_checked": 1,
    }


def test_absent_pin_never_reads_or_uses_untrusted_manifest(tmp_path):
    assert observe(tmp_path, None)["reason"] == "trusted_manifest_digest_not_supplied"
    assert observe(tmp_path, "secret")["status"] == "INCOMPLETE"
    assert observe(tmp_path, "F" * 64)["status"] == "INCOMPLETE"


def test_mismatched_manifest_pin_definitely_fails(tmp_path):
    pin = _fixture(tmp_path)
    wrong = "f" * 64 if pin != "f" * 64 else "e" * 64
    assert observe(tmp_path, wrong) == {
        "status": "FAIL", "reason": "manifest_digest_mismatch",
        "files_checked": 0,
    }


def test_matching_manifest_with_mutated_runtime_file_fails(tmp_path):
    pin = _fixture(tmp_path)
    (tmp_path / "agent/probe.py").write_text("changed")
    assert observe(tmp_path, pin) == {
        "status": "FAIL", "reason": "listed_runtime_file_mismatch",
        "files_checked": 1,
    }


@pytest.mark.parametrize("name", ["missing", "symlink", "directory", "parent_symlink"])
def test_missing_or_untrusted_files_fail_closed(tmp_path, name):
    pin = _fixture(tmp_path)
    selected = tmp_path / "agent/probe.py"
    if name == "missing":
        selected.unlink()
    elif name == "symlink":
        selected.unlink()
        selected.symlink_to(tmp_path / MANIFEST)
    elif name == "directory":
        selected.unlink()
        selected.mkdir()
    else:
        target = tmp_path / "other"
        (tmp_path / "agent").rename(target)
        (tmp_path / "agent").symlink_to(target, target_is_directory=True)
    result = observe(tmp_path, pin)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "manifest_or_file_unverifiable"


def test_symlinked_or_nonregular_manifest_never_followed(tmp_path):
    _fixture(tmp_path)
    manifest = tmp_path / MANIFEST
    manifest.rename(tmp_path / "backup")
    manifest.symlink_to(tmp_path / "backup")
    assert observe(tmp_path, hashlib.sha256((tmp_path / "backup").read_bytes()).hexdigest())[
        "status"] == "INCOMPLETE"


def test_pinned_invalid_schema_is_not_a_success(tmp_path):
    pin = _fixture(tmp_path)
    manifest = tmp_path / MANIFEST
    data = json.loads(manifest.read_text())
    data["runtime_files"][0]["path"] = "../private.env"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    updated_pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert updated_pin != pin
    result = observe(tmp_path, updated_pin)
    assert result["status"] == "INCOMPLETE"


def test_manifest_size_limit_fails_without_reading_arbitrary_bytes(tmp_path):
    manifest = tmp_path / MANIFEST
    manifest.write_bytes(b"{" + b" " * (2 * 1024 * 1024))
    pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert observe(tmp_path, pin)["status"] == "INCOMPLETE"


def test_runtime_file_size_limit_is_enforced(tmp_path):
    pin = _fixture(tmp_path)
    selected = tmp_path / "agent/probe.py"
    with selected.open("r+b") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    assert observe(tmp_path, pin)["status"] == "INCOMPLETE"


def test_no_stdout_secrets_or_paths_for_drift(tmp_path, monkeypatch, capsys):
    pin = _fixture(tmp_path)
    (tmp_path / "agent/probe.py").write_bytes(b"SECRET_MY_HOST_PASSWORD")
    from tools import sraf_airgap_off2_manifest_check as cli
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--expected-manifest-sha256", pin]) == 1
    output = capsys.readouterr().out
    assert "listed_runtime_file_mismatch" in output
    assert all(secret not in output for secret in (
        "SECRET_MY_HOST_PASSWORD", str(tmp_path), "agent/probe.py", pin,
    ))
    assert "NOT_RELEASE_OR_AIRGAP_ATTESTATION" in output


def test_cli_without_pin_exits_two_with_fixed_incomplete(tmp_path, monkeypatch, capsys):
    from tools import sraf_airgap_off2_manifest_check as cli
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 2
    assert capsys.readouterr().out.startswith("SRAF_OFF2_PROVENANCE=INCOMPLETE")


def test_root_symlink_fail_closed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    pin = _fixture(real)
    root = tmp_path / "alias"
    root.symlink_to(real, target_is_directory=True)
    assert observe(root, pin)["status"] == "INCOMPLETE"
