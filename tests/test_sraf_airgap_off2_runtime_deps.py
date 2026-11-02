"""OFF-2 passive direct distribution METADATA reader: bounded and nofollow."""
from __future__ import annotations

import json
from pathlib import Path
import os

import pytest

from tools import sraf_airgap_off2_runtime_deps as target


def add_dist(site: Path, name: str, version: str, *, content: str | None = None):
    dist = site / f"{name}-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        content if content is not None
        else f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\nDescription text\n",
        encoding="utf-8",
    )
    return dist


@pytest.fixture
def inventory(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "FastAPI>=0.115.0\npython-docx==1.1.2\npyodbc>=5.0.0\n", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    fastapi = add_dist(site, "fastapi", "0.116.0")
    docx = add_dist(site, "python_docx", "1.1.2", content=
                    "Metadata-Version: 2.1\nName: python-docx\nVersion: 1.1.2\n\n")
    pyodbc = add_dist(site, "pyodbc", "5.2.0")
    return tmp_path, site, fastapi, docx, pyodbc


def result(root: Path, site: Path):
    return target.observe(root, locations=(str(site),))


def test_all_direct_metadata_present_still_only_partial(inventory):
    root, site, _, _, _ = inventory
    value = result(root, site)
    assert value == {
        "schema": target.SCHEMA, "scope": target.SCOPE,
        "status": "PASS_PARTIAL", "reason": "direct_distribution_metadata_observed_only",
        "requirements_checked": 3, "installed_direct_count": 3,
        "missing_direct_count": 0, "unlocked_direct_count": 2,
        "exact_text_matches": 1, "transitive_closure": "NOT_TESTED",
        "wheelhouse_compatibility": "NOT_TESTED", "package_imports": "NOT_TESTED",
        "production_release_ready": False,
    }
    encoded = json.dumps(value)
    assert "fastapi" not in encoded and "pyodbc" not in encoded
    assert "python-docx" not in encoded and str(root) not in encoded


def test_missing_distribution_is_incomplete(inventory):
    root, site, _, _, pyodbc = inventory
    (pyodbc / "METADATA").unlink()
    pyodbc.rmdir()
    value = result(root, site)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "direct_distribution_metadata_missing"
    assert value["missing_direct_count"] == 1


def test_exact_version_text_mismatch_is_incomplete(inventory):
    root, site, _, docx, _ = inventory
    (docx / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: python-docx\nVersion: 1.1.3\n\n")
    value = result(root, site)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "installed_distribution_metadata_unverifiable"


@pytest.mark.parametrize("kind", [
    "duplicate", "symlink_dir", "symlink_meta", "oversized", "truncated",
    "header_no_version", "duplicate_name", "path_version", "wrong_name",
    "bad_encoding",
])
def test_bounded_selected_metadata_fails_closed(inventory, tmp_path, kind):
    root, site, fastapi, _, _ = inventory
    if kind == "duplicate":
        add_dist(site, "fastapi", "0.117.0")
    elif kind == "symlink_dir":
        (fastapi / "METADATA").unlink()
        fastapi.rmdir()
        fastapi.symlink_to(tmp_path / "other", target_is_directory=True)
    elif kind == "symlink_meta":
        other = tmp_path / "secret"
        other.write_text("Metadata-Version: 2.1\nName: fastapi\nVersion: 0.116.0\n\n")
        (fastapi / "METADATA").unlink()
        (fastapi / "METADATA").symlink_to(other)
    elif kind == "oversized":
        (fastapi / "METADATA").write_bytes(b"x" * (target._MAX_METADATA_BYTES + 1))
    elif kind == "truncated":
        (fastapi / "METADATA").write_text("Name: fastapi\nVersion: 0.116.0")
    elif kind == "header_no_version":
        (fastapi / "METADATA").write_text("Name: fastapi\n\n")
    elif kind == "duplicate_name":
        (fastapi / "METADATA").write_text(
            "Name: fastapi\nName: fastapi\nVersion: 0.116.0\n\n")
    elif kind == "path_version":
        (fastapi / "METADATA").write_text(
            "Name: fastapi\nVersion: /private/secret\n\n")
    elif kind == "wrong_name":
        (fastapi / "METADATA").write_text(
            "Name: unrelated\nVersion: 0.116.0\n\n")
    else:
        (fastapi / "METADATA").write_bytes(b"\xff")
    value = result(root, site)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "installed_distribution_metadata_unverifiable"
    assert "private" not in json.dumps(value).lower()


def test_safe_folded_unrelated_metadata_is_accepted(inventory):
    root, site, fastapi, _, _ = inventory
    (fastapi / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fastapi\nVersion: 0.116.0\n"
        "Description: multi-line narrative\n detail without identity change\n\n")
    assert result(root, site)["status"] == "PASS_PARTIAL"


def test_folded_identity_header_is_never_accepted(inventory):
    root, site, fastapi, _, _ = inventory
    (fastapi / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fastapi\n extra identity bytes\n"
        "Version: 0.116.0\n\n")
    assert result(root, site)["reason"] == "installed_distribution_metadata_unverifiable"


def test_unrelated_oversized_metadata_must_not_be_read(inventory):
    root, site, _, _, _ = inventory
    unrelated = add_dist(site, "unrelated", "9.9")
    (unrelated / "METADATA").write_bytes(b"SECRET_LARGE_PAYLOAD" * 131072)
    value = result(root, site)
    assert value["status"] == "PASS_PARTIAL"
    assert "SECRET" not in json.dumps(value)


def test_one_million_byte_selected_metadata_always_fails_closed(inventory):
    root, site, fastapi, _, _ = inventory
    with (fastapi / "METADATA").open("wb") as stream:
        stream.write(b"Metadata-Version: 2.1\nName: fastapi\nVersion: 0.116.0\n\n")
        stream.write(b"x" * target._MAX_METADATA_BYTES)
    value = result(root, site)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "installed_distribution_metadata_unverifiable"


@pytest.mark.parametrize("req", [
    "fastapi>=0.1\nFastAPI>=0.2\n",
    "fastapi[all]==1.0\n",
    "secret-package @ file:///private/secret\n",
    "-r other.txt\n",
    "--extra-index-url https://example.invalid\n",
    'foo==1.0; python_version >= "3.10"\n',
    "\ufefffoo==1.0\n",
    "foo==1.0\x00secret\n",
    "# only comment\n",
])
def test_bad_requirements_do_not_probe_any_distribution(inventory, req, monkeypatch):
    root, site, _, _, _ = inventory
    (root / "requirements.txt").write_text(req)
    calls = []
    original = target._metadata_snapshot
    monkeypatch.setattr(target, "_metadata_snapshot",
                        lambda *args: (calls.append(True), original(*args))[1])
    value = result(root, site)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "requirements_input_unverifiable"
    assert calls == []


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "directory", "bad_utf8"])
def test_nofollow_requirement_file_validation(inventory, tmp_path, kind):
    root, site, _, _, _ = inventory
    source = root / "requirements.txt"
    if kind == "missing":
        source.unlink()
    elif kind == "symlink":
        other = tmp_path / "other"
        other.write_text("fastapi==1.0\n")
        source.unlink()
        source.symlink_to(other)
    elif kind == "oversized":
        source.write_bytes(b"x" * (target.MAX_REQUIREMENTS_BYTES + 1))
    elif kind == "directory":
        source.unlink()
        source.mkdir()
    else:
        source.write_bytes(b"\xff")
    assert result(root, site)["reason"] == "requirements_input_unverifiable"


def test_symlinked_site_dir_or_parent_is_not_traversed(inventory, tmp_path):
    root, site, _, _, _ = inventory
    entry = tmp_path / "alias-site"
    entry.symlink_to(site, target_is_directory=True)
    value = result(root, entry)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "installed_distribution_metadata_unverifiable"


def test_scan_count_is_bounded_without_loading_irrelevant_metadata(inventory):
    root, site, _, _, _ = inventory
    for i in range(target._MAX_DISTS_SCAN + 1):
        (site / f"junk_{i}.dist-info").mkdir()
    value = result(root, site)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "installed_distribution_metadata_unverifiable"


def test_cli_reports_fixed_json_and_blocks_extra_arguments(inventory, monkeypatch, capsys):
    root, site, _, _, _ = inventory
    monkeypatch.chdir(root)
    monkeypatch.setattr(target, "_locations", lambda: (str(site),))
    assert target.main([]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "PASS_PARTIAL"
    assert str(root) not in output
    with pytest.raises(SystemExit) as exc:
        target.main(["--live-report"])
    assert exc.value.code == 2


def test_unknown_python_install_locations_fail_closed(inventory, monkeypatch):
    root, _, _, _, _ = inventory
    monkeypatch.setattr(target.sysconfig, "get_paths",
                        lambda: {"purelib": "../private", "platlib": "relative"})
    value = target.observe(root)
    assert value["status"] == "INCOMPLETE"
    assert value["reason"] == "installed_distribution_metadata_unverifiable"
