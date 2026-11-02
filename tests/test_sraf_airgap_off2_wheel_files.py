"""OFF-2 local-only, pin-required wheel byte integrity checks."""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
import zipfile
from pathlib import Path

import pytest

from tools.sraf_airgap_off2_wheel_files import MANIFEST, observe, main

WHEEL = "example_pkg-1.0-py3-none-any.whl"

DIST_INFO = "example_pkg-1.0.dist-info"


def _wheel_bytes(*, metadata_name: str = "example-pkg",
                 include_wheel: bool = True,
                 include_metadata: bool = True,
                 extra_name: str | None = None) -> bytes:
    # A tiny *synthetic* structurally valid Wheel archive for parser tests;
    # this is NOT a genuine package, release, dependency or live acceptance.
    content = BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("example_pkg/__init__.py", "")
        if include_wheel:
            z.writestr(f"{DIST_INFO}/WHEEL",
                       "Wheel-Version: 1.0\nGenerator: synthetic-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        if include_metadata:
            z.writestr(f"{DIST_INFO}/METADATA",
                       f"Metadata-Version: 2.1\nName: {metadata_name}\nVersion: 1.0\n")
        if extra_name:
            z.writestr(extra_name, "UNTRUSTED")
    return content.getvalue()


def _repin_wheel(root: Path, data: bytes) -> str:
    (root / "wheelhouse" / WHEEL).write_bytes(data)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    manifest["wheels"][0]["size"] = len(data)
    manifest["wheels"][0]["sha256"] = hashlib.sha256(data).hexdigest()
    raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (root / MANIFEST).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()




def _fixture(root: Path) -> str:
    folder = root / "wheelhouse"
    folder.mkdir()
    data = _wheel_bytes()
    (folder / WHEEL).write_bytes(data)
    manifest = {
        "schema_version": 1, "repository": "hun186/poc-agent",
        "wheels": [{"filename": WHEEL, "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()}],
    }
    payload = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (root / MANIFEST).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_exact_pinned_listed_wheel_bytes_only_partial(tmp_path):
    pin = _fixture(tmp_path)
    assert observe(tmp_path, pin) == {
        "status": "PASS_PARTIAL", "reason": "pinned_wheel_bytes_and_basic_metadata_only",
        "wheels_checked": 1,
    }



@pytest.mark.parametrize("data,description", [
    (b"random bytes but correct external SHA", "arbitrary_binary"),
    (_wheel_bytes(include_wheel=False), "missing_wheel"),
    (_wheel_bytes(include_metadata=False), "missing_metadata"),
    (_wheel_bytes(metadata_name="forged-package"), "name_mismatch"),
    (_wheel_bytes(extra_name="../outside.py"), "zip_traversal"),
    (_wheel_bytes(extra_name="example_pkg/../escape.py"), "nested_zip_traversal"),
])
def test_pinned_bytes_with_invalid_wheel_archive_fail_closed(tmp_path, data, description):
    _fixture(tmp_path)
    pin = _repin_wheel(tmp_path, data)
    result = observe(tmp_path, pin)
    assert result == {
        "status": "INCOMPLETE",
        "reason": "wheel_archive_structure_invalid",
        "wheels_checked": 1,
    }, description


def test_duplicate_archive_member_rejected(tmp_path):
    _fixture(tmp_path)
    content = BytesIO()
    with zipfile.ZipFile(content, "w") as z:
        z.writestr(f"{DIST_INFO}/WHEEL", "Wheel-Version: 1.0\n")
        z.writestr(f"{DIST_INFO}/METADATA",
                   "Metadata-Version: 2.1\nName: example-pkg\nVersion: 1.0\n")
        with pytest.warns(UserWarning):
            z.writestr(f"{DIST_INFO}/WHEEL", "Wheel-Version: 1.0\n")
    pin = _repin_wheel(tmp_path, content.getvalue())
    assert observe(tmp_path, pin)["reason"] == "wheel_archive_structure_invalid"


def test_missing_or_invalid_external_pin_never_opens_trust(tmp_path):
    _fixture(tmp_path)
    for invalid in (None, "", "0" * 63, "F" * 64, "invalid"):
        assert observe(tmp_path, invalid) == {
            "status": "INCOMPLETE",
            "reason": "trusted_wheel_inventory_digest_not_supplied",
            "wheels_checked": 0,
        }


def test_mutated_file_detected(tmp_path):
    pin = _fixture(tmp_path)
    (tmp_path / "wheelhouse" / WHEEL).write_bytes(b"mutation")
    assert observe(tmp_path, pin)["reason"] == "wheel_file_mismatch"


def test_wrong_manifest_pin_is_fail_not_pass(tmp_path):
    pin = _fixture(tmp_path)
    wrong = "0" * 64 if pin != "0" * 64 else "1" * 64
    assert observe(tmp_path, wrong) == {
        "status": "FAIL", "reason": "wheel_inventory_digest_mismatch",
        "wheels_checked": 0,
    }


@pytest.mark.parametrize("case", ["extra", "missing", "symlink", "folder_link"])
def test_directory_extras_or_unsafe_files_never_pass(tmp_path, case):
    pin = _fixture(tmp_path)
    folder = tmp_path / "wheelhouse"
    wheel = folder / WHEEL
    if case == "extra":
        (folder / "rogue.whl").write_bytes(b"untrusted")
    elif case == "missing":
        wheel.unlink()
    elif case == "symlink":
        wheel.unlink()
        wheel.symlink_to(tmp_path / MANIFEST)
    else:
        original = tmp_path / "source"
        folder.rename(original)
        folder.symlink_to(original, target_is_directory=True)
    result = observe(tmp_path, pin)
    assert result["status"] == "INCOMPLETE"


@pytest.mark.parametrize("change", [
    lambda d: d.update(repository="forged/repo"),
    lambda d: d["wheels"][0].update(filename="../private.whl"),
    lambda d: d["wheels"][0].update(sha256="secret"),
    lambda d: d["wheels"][0].update(size=True),
    lambda d: d["wheels"].append(dict(d["wheels"][0])),
    lambda d: d["wheels"].clear(),
])
def test_pinned_but_invalid_inventory_not_accepted(tmp_path, change):
    _fixture(tmp_path)
    path = tmp_path / MANIFEST
    data = json.loads(path.read_text())
    change(data)
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    assert observe(tmp_path, pin) == {
        "status": "INCOMPLETE", "reason": "wheel_inventory_or_files_unverifiable",
        "wheels_checked": 0,
    }


def test_duplicate_json_property_and_boolean_version_rejected(tmp_path):
    _fixture(tmp_path)
    path = tmp_path / MANIFEST
    for raw in (
        b'{"schema_version":1,"schema_version":1,"repository":"hun186/poc-agent","wheels":[]}',
        b'{"schema_version":true,"repository":"hun186/poc-agent","wheels":[]}',
    ):
        path.write_bytes(raw)
        pin = hashlib.sha256(raw).hexdigest()
        assert observe(tmp_path, pin)["status"] == "INCOMPLETE"


def test_manifest_symlink_not_followed(tmp_path):
    pin = _fixture(tmp_path)
    path = tmp_path / MANIFEST
    other = tmp_path / "other.json"
    path.rename(other)
    path.symlink_to(other)
    assert observe(tmp_path, pin)["status"] == "INCOMPLETE"


def test_redacted_cli_and_no_mutation(tmp_path, monkeypatch, capsys):
    pin = _fixture(tmp_path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.chdir(tmp_path)
    assert main(["--expected-manifest-sha256", pin]) == 0
    output = capsys.readouterr().out
    assert output.startswith("SRAF_OFF2_WHEELS=PASS_PARTIAL")
    assert "NOT_DEPENDENCY_OR_AIRGAP_ATTESTATION" in output
    assert pin not in output and WHEEL not in output and str(tmp_path) not in output
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
