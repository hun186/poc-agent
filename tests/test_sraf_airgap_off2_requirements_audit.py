"""OFF-2 stdlib-only direct requirement pin audit tests (no network)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.sraf_airgap_off2_requirements_audit import (
    SCOPE, observe, main,
)


def test_current_requirements_are_not_version_locked():
    root = Path(__file__).resolve().parents[1]
    value = observe(root)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "direct_versions_unpinned"
    assert value["requirements_checked"] > 0
    assert value["unpinned_count"] > 0


def test_exact_literal_pins_are_only_partial(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# explicit subset\nfastapi==0.115.0\nPydantic==2.9.2\n",
        encoding="utf-8",
    )
    assert observe(tmp_path) == {
        "status": "PASS_PARTIAL", "reason": "direct_versions_pinned_only",
        "requirements_checked": 2, "unpinned_count": 0,
    }


def test_unpinned_constraints_and_wildcards_never_pass(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "fastapi>=0.115.0\nrequests~=2.31\nuvicorn==0.30.*\n",
        encoding="utf-8",
    )
    assert observe(tmp_path) == {
        "status": "INCOMPLETE", "reason": "direct_versions_unpinned",
        "requirements_checked": 3, "unpinned_count": 3,
    }


@pytest.mark.parametrize("line", [
    "-r extra.txt", "--extra-index-url https://example.invalid",
    "-e .", "https://example.invalid/mypkg.whl", "git+https://example.invalid/repo",
    "fastapi[all]==0.115.0", 'fastapi==0.115.0; python_version >= "3.11"',
    "fastapi==0.115.0 # note", "fastapi==0.115.0\\",
    "fastapi @ file:///tmp/secret", "a==x", "a==1.0\x00secret",
])
def test_unsupported_directive_never_counted_as_locked(tmp_path, line):
    (tmp_path / "requirements.txt").write_text(line + "\n")
    value = observe(tmp_path)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] in {"requirement_syntax_unsupported",
                                "direct_versions_unpinned"}


@pytest.mark.parametrize("kind", ["missing", "symlink", "directory", "oversized", "bad_utf8"])
def test_unsafe_or_unreadable_requirements_fail_closed(tmp_path, kind):
    target = tmp_path / "requirements.txt"
    if kind == "symlink":
        other = tmp_path / "other.txt"
        other.write_text("fastapi==1.0\n")
        target.symlink_to(other)
    elif kind == "directory":
        target.mkdir()
    elif kind == "oversized":
        target.write_bytes(b"#" * (64 * 1024 + 1))
    elif kind == "bad_utf8":
        target.write_bytes(b"\xff")
    elif kind != "missing":
        raise AssertionError(kind)
    assert observe(tmp_path) == {
        "status": "INCOMPLETE", "reason": "requirement_input_unverifiable",
        "requirements_checked": 0, "unpinned_count": 0,
    }


def test_no_runtime_mutation_or_raw_requirement_output(tmp_path, monkeypatch, capsys):
    path = tmp_path / "requirements.txt"
    content = b"SECRET_INSTALL_ENDPOINT>=1.0\n"
    path.write_bytes(content)
    monkeypatch.chdir(tmp_path)
    assert main([]) == 2
    output = capsys.readouterr().out
    assert output.startswith("SRAF_OFF2_DEPS=INCOMPLETE")
    assert SCOPE in output
    assert "SECRET_INSTALL_ENDPOINT" not in output
    assert str(tmp_path) not in output
    assert path.read_bytes() == content


def test_empty_and_unsupported_bom_fail_closed(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# comment\n")
    assert observe(tmp_path)["reason"] == "requirements_empty"
    path.write_bytes(b"\xef\xbb\xbffastapi==1.0\n")
    assert observe(tmp_path)["reason"] == "requirement_syntax_unsupported"
