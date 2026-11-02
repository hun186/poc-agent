"""OFF-2 selected-interpreter installed direct distribution metadata only."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off2_runtime_deps as target


class FakeDist:
    def __init__(self, name, version):
        self.metadata = {"Name": name} if name is not None else {}
        self.version = version


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text(
        "FastAPI>=0.115.0\n"
        "python-docx==1.1.2\n"
        "pyodbc>=5.0.0\n", encoding="utf-8"
    )
    records = [
        FakeDist("fastapi", "0.116.0"),
        FakeDist("python_docx", "1.1.2"),
        FakeDist("PyODBC", "5.2.0"),
    ]
    called = []
    def distributions(*, path):
        called.append(tuple(path))
        return iter(records)
    monkeypatch.setattr(target.metadata, "distributions", distributions)
    return tmp_path, records, called


def test_all_installed_direct_metadata_is_partial_even_with_open_ranges(inventory):
    root, _, calls = inventory
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result == {
        "schema": target.SCHEMA, "scope": target.SCOPE,
        "status": "PASS_PARTIAL", "reason": "direct_distribution_metadata_observed_only",
        "requirements_checked": 3, "installed_direct_count": 3,
        "missing_direct_count": 0, "unlocked_direct_count": 2,
        "exact_text_matches": 1, "transitive_closure": "NOT_TESTED",
        "wheelhouse_compatibility": "NOT_TESTED", "package_imports": "NOT_TESTED",
        "production_release_ready": False,
    }
    assert calls == [("/private/runtime/lib",)]
    output = json.dumps(result)
    assert "fastapi" not in output and "pyodbc" not in output
    assert "python-docx" not in output and "/private" not in output


def test_missing_installed_metadata_is_incomplete_without_names(inventory):
    root, records, _ = inventory
    records.pop()
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "direct_distribution_metadata_missing"
    assert result["installed_direct_count"] == 2
    assert result["missing_direct_count"] == 1
    assert "pyodbc" not in json.dumps(result).lower()


def test_exact_text_mismatch_is_incomplete_even_when_present(inventory):
    root, records, _ = inventory
    records[1] = FakeDist("python-docx", "1.1.3")
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "exact_direct_version_text_mismatch"
    assert result["exact_text_matches"] == 0
    assert result["installed_direct_count"] == 3


@pytest.mark.parametrize("kind", [
    "duplicate_name", "duplicate_canonical_name", "missing_version",
    "path_version", "long_version", "too_many_dists",
])
def test_malformed_or_ambiguous_installed_metadata_is_never_success(
        inventory, monkeypatch, kind):
    root, records, _ = inventory
    if kind == "duplicate_name":
        records.append(FakeDist("fastapi", "0.116.0"))
    elif kind == "duplicate_canonical_name":
        records.append(FakeDist("PYTHON.DOCX", "1.1.2"))
    elif kind == "missing_version":
        records[0] = FakeDist("FastAPI", "")
    elif kind == "path_version":
        records[0] = FakeDist("fastapi", "/private/secret")
    elif kind == "long_version":
        records[0] = FakeDist("fastapi", "x" * 500)
    elif kind == "too_many_dists":
        records.extend(FakeDist("unrelated", "1.0") for _ in range(4097))
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "installed_distribution_metadata_unverifiable"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("requirement", [
    "FastAPI==0.115.0\nfastapi>=0.116.0\n",
    "fastapi[all]>=0.115.0\n",
    "secret-package @ file:///private/path\n",
    "--extra-index-url https://example.invalid\n",
    "git+https://example.invalid/code\n",
    "foo==1.0; python_version >= '3.10'\n",
    "foo==1.0\\\n",
    "\ufefffoo==1.0\n",
    "fake==1.0\x00thing\n",
    "# comment only\n",
])
def test_reject_unsupported_requirements_before_scanning(inventory, requirement):
    root, _, calls = inventory
    (root / "requirements.txt").write_text(requirement)
    value = target.observe(root, locations=("/private/runtime/lib",))
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "requirements_input_unverifiable"
    assert not calls


@pytest.mark.parametrize("failure", ["missing", "symlink", "oversize", "bad_utf8", "directory"])
def test_required_file_is_no_follow_bounded(inventory, tmp_path, failure):
    root, _, calls = inventory
    path = root / "requirements.txt"
    if failure == "missing":
        path.unlink()
    elif failure == "symlink":
        path.unlink()
        other = root / "secret"
        other.write_text("fastapi>=1.0\n")
        path.symlink_to(other)
    elif failure == "oversize":
        path.write_bytes(b"x" * (target.MAX_REQUIREMENTS_BYTES + 1))
    elif failure == "bad_utf8":
        path.write_bytes(b"\xff")
    elif failure == "directory":
        path.unlink()
        path.mkdir()
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "requirements_input_unverifiable"
    assert not calls


def test_untrusted_distribution_names_are_not_output_or_dependency_proof(inventory):
    root, records, _ = inventory
    records.append(FakeDist("PRIVATE_SECRET_INTERNAL_NAME", "1.0"))
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result["status"] == "PASS_PARTIAL"
    assert "PRIVATE_SECRET_INTERNAL_NAME" not in json.dumps(result)
    assert result["transitive_closure"] == "NOT_TESTED"
    assert result["wheelhouse_compatibility"] == "NOT_TESTED"


def test_odd_install_location_fails_closed(inventory, monkeypatch):
    root, _, calls = inventory
    monkeypatch.setattr(target.sysconfig, "get_paths",
                        lambda: {"purelib": "../private", "platlib": "elsewhere"})
    result = target.observe(root)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "installed_distribution_metadata_unverifiable"
    assert not calls


def test_cli_is_redacted_and_fails_extra_args(inventory, monkeypatch, capsys):
    root, _, _ = inventory
    monkeypatch.chdir(root)
    assert target.main([]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == target.SCHEMA
    assert data["status"] == "PASS_PARTIAL"
    assert "FastAPI" not in out and str(root) not in out
    with pytest.raises(SystemExit) as exc:
        target.main(["--live-report"])
    assert exc.value.code == 2


def test_installed_metadata_does_not_import_target_modules(inventory, monkeypatch):
    root, _, _ = inventory
    called = []
    def forbidding_import(name, *args, **kwargs):
        called.append(name)
        raise AssertionError("must not import application dependencies")
    monkeypatch.setattr(target, "__import_target_forbidden", forbidding_import, raising=False)
    result = target.observe(root, locations=("/private/runtime/lib",))
    assert result["status"] == "PASS_PARTIAL"
    assert not called
