"""Optional user-site OFF-2 metadata inventory: synthetic bounded, nofollow."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import sraf_airgap_off2_user_site as target

def add_dist(site: Path, name: str, version: str) -> Path:
    folder = site / f"{name}-{version}.dist-info"
    folder.mkdir()
    (folder / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def locations(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "requirements.txt").write_text(
        "# public direct requirements\n"
        "fastapi>=0.115.0\n"
        "smolagents>=1.0.0\n"
        "pyodbc>=5.0.0\n", encoding="utf-8")
    scheme = tmp_path / "scheme"
    scheme.mkdir()
    user = tmp_path / "user"
    user.mkdir()
    add_dist(scheme, "fastapi", "0.116.0")
    add_dist(user, "smolagents", "1.5.0")
    add_dist(user, "pyodbc", "5.2.0")
    monkeypatch.setattr(target.site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(target.site, "getusersitepackages", lambda: str(user))
    monkeypatch.setattr(target.sys, "path", [*target.sys.path, str(user)])
    return root, scheme, user


def audit(locations):
    root, scheme, user = locations
    return target.observe(root, scheme_paths=(str(scheme),), user_path=str(user))


def test_user_site_fallback_is_only_partial_without_runtime_authority(locations):
    root, scheme, user = locations
    res = audit(locations)
    assert res["schema"] == target.SCHEMA
    assert res["status"] == "PASS_PARTIAL"
    assert res["reason"] == "direct_metadata_observed_with_user_site_fallback_only"
    assert res["requirements_checked"] == 3
    assert res["installed_direct_count"] == 3
    assert res["scheme_installed_direct_count"] == 1
    assert res["user_site_fallback_direct_count"] == 2
    assert res["missing_direct_count"] == 0
    assert res["missing_direct_positions"] == []
    assert res["metadata_search_scope"] == target.SEARCH
    assert res["user_site_active"] is True
    assert res["user_site_release_attested"] is False
    assert res["package_imports"] == "NOT_TESTED"
    assert res["transitive_closure"] == "NOT_TESTED"
    assert res["wheelhouse_compatibility"] == "NOT_TESTED"
    assert res["production_release_ready"] is False
    assert str(root) not in json.dumps(res)
    assert str(user) not in json.dumps(res)
    assert "smolagents" not in json.dumps(res).lower()


def test_user_site_disabled_is_not_counted_even_if_metadata_exists(locations, monkeypatch):
    monkeypatch.setattr(target.site, "ENABLE_USER_SITE", False)
    res = audit(locations)
    assert res["status"] == "INCOMPLETE"
    assert res["reason"] == "active_user_site_unavailable"
    assert res["installed_direct_count"] == 1
    assert res["user_site_active"] is False
    assert res["missing_direct_positions"] == []


def test_user_site_not_in_sys_path_cannot_be_called_active(locations, monkeypatch):
    root, scheme, user = locations
    monkeypatch.setattr(target.sys, "path", [str(scheme)])
    res = audit(locations)
    assert res["status"] == "INCOMPLETE"
    assert res["reason"] == "active_user_site_unavailable"


@pytest.mark.parametrize("which", ["wrong_spelling", "not_absolute", "parent", "same_as_scheme"])
def test_unsafe_site_path_does_not_override_scheme(locations, which):
    root, scheme, user = locations
    path = {
        "wrong_spelling": str(user) + "x",
        "not_absolute": "site-packages",
        "parent": str(user / ".."),
        "same_as_scheme": str(scheme),
    }[which]
    res = target.observe(root, scheme_paths=(str(scheme),), user_path=path)
    assert res["status"] == "INCOMPLETE"
    assert res["reason"] == "active_user_site_unavailable"
    assert res["user_site_fallback_direct_count"] == 0


@pytest.mark.parametrize("which", ["symlink_site", "symlink_metadata", "oversized_metadata", "wrong_metadata", "duplicate"])
def test_bad_user_site_meta_fails_closed(locations, tmp_path, which):
    root, scheme, user = locations
    if which == "symlink_site":
        alias = tmp_path / "alias"
        alias.symlink_to(user, target_is_directory=True)
        target.sys.path.append(str(alias))
        user_path = str(alias)
    else:
        user_path = str(user)
        path = user / "smolagents-1.5.0.dist-info"
        meta = path / "METADATA"
        if which == "symlink_metadata":
            copy = tmp_path / "secret"
            meta.rename(copy)
            meta.symlink_to(copy)
        elif which == "oversized_metadata":
            meta.write_bytes(b"x" * (1024 * 1024 + 1))
        elif which == "wrong_metadata":
            meta.write_text("Metadata-Version: 2.1\nName: secret\nVersion: 1.5.0\n\n")
        elif which == "duplicate":
            add_dist(user, "smolagents", "1.6.0")
    res = target.observe(root, scheme_paths=(str(scheme),), user_path=user_path)
    assert res["status"] == "INCOMPLETE"
    assert res["reason"] == "user_site_distribution_metadata_unverifiable"
    assert res["missing_direct_positions"] == []
    assert res["user_site_release_attested"] is False
    assert "secret" not in json.dumps(res)


def test_missing_user_site_dist_reports_public_requirement_index(locations):
    root, scheme, user = locations
    path = user / "pyodbc-5.2.0.dist-info"
    (path / "METADATA").unlink()
    path.rmdir()
    res = audit(locations)
    assert res["status"] == "INCOMPLETE"
    assert res["reason"] == "direct_distribution_metadata_missing"
    assert res["missing_direct_positions"] == [3]
    assert res["installed_direct_count"] == 2
    assert res["scheme_installed_direct_count"] == 1
    assert res["user_site_fallback_direct_count"] == 1
    assert "pyodbc" not in json.dumps(res)


def test_scheme_precedence_skips_duplicate_unrelated_user_site_metadata(locations):
    root, scheme, user = locations
    duplicate = add_dist(user, "fastapi", "0.999")
    (duplicate / "METADATA").write_bytes(b"SECRET" * (1024 * 1024))
    res = audit(locations)
    assert res["status"] == "PASS_PARTIAL"
    assert res["scheme_installed_direct_count"] == 1
    assert res["user_site_fallback_direct_count"] == 2


def test_no_user_site_needed_if_scheme_contains_all_direct_packages(locations, monkeypatch):
    root, scheme, user = locations
    add_dist(scheme, "smolagents", "1.5.0")
    add_dist(scheme, "pyodbc", "5.2.0")
    monkeypatch.setattr(target.site, "ENABLE_USER_SITE", False)
    res = audit(locations)
    assert res["status"] == "PASS_PARTIAL"
    assert res["reason"] == "direct_metadata_in_scheme_only"
    assert res["user_site_fallback_direct_count"] == 0
    assert res["user_site_active"] is False


def test_cli_prints_only_redacted_fixed_json(locations, monkeypatch, capsys):
    root, scheme, user = locations
    monkeypatch.chdir(root)
    monkeypatch.setattr(target.scheme, "_locations", lambda: (str(scheme),))
    assert target.main([]) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["status"] == "PASS_PARTIAL"
    assert str(user) not in output and str(root) not in output
    with pytest.raises(SystemExit) as exc:
        target.main(["--probe-sql"])
    assert exc.value.code == 2
