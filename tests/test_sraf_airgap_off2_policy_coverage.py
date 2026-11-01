"""OFF-2 minimum operator entrypoint policy tests: local only, no sockets."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sraf_airgap_off2_policy_coverage import (
    POLICY, REQUIRED_OPERATOR_FILES, observe, main,
)


def _fixture(root: Path, *, covered: bool = True):
    for name in REQUIRED_OPERATOR_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# harmless test file\n", encoding="utf-8")
    policy = {
        "schema_version": 1,
        "repository": "hun186/poc-agent",
        "managed_roots": ["agent"],
        "managed_files": [path for path in REQUIRED_OPERATOR_FILES
                          if not path.startswith("tools/")] if covered else [],
        "release_tool_files": [path for path in REQUIRED_OPERATOR_FILES
                               if path.startswith("tools/")] if covered else [],
        "allowed_runtime_extra_globs": [],
        "guarded_root_extensions": [".py", ".sh", ".pth"],
    }
    (root / POLICY).write_text(json.dumps(policy), encoding="utf-8")


def test_repository_current_reviewed_policy_covers_minimum_operator_tools():
    # This is checkout-local policy selection only; no services or signed
    # bundle validation, and it must never be promoted to FULL_LIVE.
    root = Path(__file__).resolve().parents[1]
    assert observe(root) == {
        "status": "PASS_PARTIAL",
        "reason": "minimum_policy_selection_only",
        "files_checked": len(REQUIRED_OPERATOR_FILES),
        "unlisted_count": 0,
    }


def test_all_explicit_paths_are_only_partial_policy_selection(tmp_path):
    _fixture(tmp_path)
    assert observe(tmp_path) == {
        "status": "PASS_PARTIAL", "reason": "minimum_policy_selection_only",
        "files_checked": len(REQUIRED_OPERATOR_FILES), "unlisted_count": 0,
    }


def test_realistic_unmanaged_entrypoints_report_gap_not_pass(tmp_path):
    _fixture(tmp_path, covered=False)
    result = observe(tmp_path)
    assert result == {
        "status": "INCOMPLETE", "reason": "required_operator_tools_unlisted",
        "files_checked": len(REQUIRED_OPERATOR_FILES),
        "unlisted_count": len(REQUIRED_OPERATOR_FILES),
    }


def test_broad_directory_wildcard_does_not_replace_explicit_release_tool_list(tmp_path):
    _fixture(tmp_path)
    data = json.loads((tmp_path / POLICY).read_text())
    data["managed_roots"].append("tools")
    data["release_tool_files"] = []
    (tmp_path / POLICY).write_text(json.dumps(data))
    result = observe(tmp_path)
    assert result["status"] == "INCOMPLETE"
    assert result["unlisted_count"] == sum(
        path.startswith("tools/") for path in REQUIRED_OPERATOR_FILES)


@pytest.mark.parametrize("kind", ["missing", "symlink", "directory"])
def test_missing_or_untrusted_operator_file_is_incomplete(tmp_path, kind):
    _fixture(tmp_path)
    item = tmp_path / REQUIRED_OPERATOR_FILES[0]
    item.unlink()
    if kind == "symlink":
        item.symlink_to(tmp_path / POLICY)
    if kind == "directory":
        item.mkdir()
    assert observe(tmp_path)["reason"] == "policy_or_tool_unverifiable"


def test_symlinked_policy_never_followed(tmp_path):
    _fixture(tmp_path)
    source = tmp_path / POLICY
    source.rename(source.with_suffix(".bak"))
    source.symlink_to(source.with_suffix(".bak"))
    assert observe(tmp_path)["status"] == "INCOMPLETE"


def test_invalid_policy_and_oversized_policy_fail_closed(tmp_path):
    _fixture(tmp_path)
    policy = tmp_path / POLICY
    policy.write_text('{"arbitrary":"value"}')
    assert observe(tmp_path)["reason"] == "policy_or_tool_unverifiable"
    policy.write_bytes(b"{" + b" " * (1024 * 1024))
    assert observe(tmp_path)["status"] == "INCOMPLETE"


def test_cli_redacts_filesystem_paths_and_secret_strings(tmp_path, monkeypatch, capsys):
    _fixture(tmp_path, covered=False)
    monkeypatch.chdir(tmp_path)
    assert main() == 2
    output = capsys.readouterr().out
    assert output.startswith("SRAF_OFF2_POLICY=INCOMPLETE")
    assert "POLICY_SELECTION_ONLY_NOT_RELEASE_OR_AIRGAP_ATTESTATION" in output
    assert str(tmp_path) not in output
    assert "run_sraf_airgap_offline.sh" not in output
    assert "PASSWORD" not in output


def test_probe_does_not_modify_any_file(tmp_path):
    _fixture(tmp_path)
    before = {str(p.relative_to(tmp_path)): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    observe(tmp_path)
    after = {str(p.relative_to(tmp_path)): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
