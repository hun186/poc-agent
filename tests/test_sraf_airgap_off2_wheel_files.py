"""OFF-2 local-only, pin-required wheel byte integrity checks."""
from __future__ import annotations

import hashlib
import base64
import csv
from io import BytesIO
import json
import io
import zipfile
from pathlib import Path

import pytest

from tools.sraf_airgap_off2_wheel_files import MANIFEST, observe, main

WHEEL = "example_pkg-1.0-py3-none-any.whl"

DIST_INFO = "example_pkg-1.0.dist-info"


def _wheel_bytes(*, metadata_name: str = "example-pkg",
                 include_wheel: bool = True,
                 include_metadata: bool = True,
                 folded_license: bool = False,
                 extra_name: str | None = None,
                 record_case: str = "valid",
                 include_legacy_signature: bool = False) -> bytes:
    # Synthetic Wheel ZIP only: tests do NOT attest a real dependency bundle.
    entries: list[tuple[str, bytes]] = [("example_pkg/__init__.py", b"")]
    if include_wheel:
        entries.append((f"{DIST_INFO}/WHEEL",
                        b"Wheel-Version: 1.0\nGenerator: synthetic-test\n"
                        b"Root-Is-Purelib: true\nTag: py3-none-any\n"))
    if include_metadata:
        headers = f"Metadata-Version: 2.1\nName: {metadata_name}\nVersion: 1.0\n"
        if folded_license:
            headers += "License: BSD style\n continuation is valid\n"
        entries.append((f"{DIST_INFO}/METADATA", headers.encode("utf-8")))
    if extra_name:
        entries.append((extra_name, b"UNTRUSTED"))
    if include_legacy_signature:
        entries.append((f"{DIST_INFO}/RECORD.jws", b"UNVERIFIED_LEGACY_SIGNATURE"))

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    for i, (name, data) in enumerate(entries):
        if name == f"{DIST_INFO}/RECORD.jws":
            continue
        if record_case == "missing_entry" and i == 0:
            continue
        digest = "sha256=" + base64.urlsafe_b64encode(
            hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        if record_case == "bad_hash" and i == 0:
            digest = "sha256=" + "A" * 43
        length = str(len(data))
        if record_case == "bad_size" and i == 0:
            length = "999"
        writer.writerow((name, digest, length))
    if record_case == "extra_row":
        writer.writerow(("hidden.py", "sha256=" + "A" * 43, "0"))
    if record_case == "record_hash":
        writer.writerow((f"{DIST_INFO}/RECORD", "sha256=" + "A" * 43, "12"))
    else:
        writer.writerow((f"{DIST_INFO}/RECORD", "", ""))

    content = BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
        if record_case != "missing_record":
            record_bytes = (b"\n" * (2 * 1024 * 1024)
                            if record_case == "blank_row_bomb"
                            else out.getvalue().encode("utf-8"))
            z.writestr(f"{DIST_INFO}/RECORD", record_bytes)
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
        "status": "PASS_PARTIAL", "reason": "pinned_wheel_bytes_metadata_record_only",
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



def test_legitimate_folded_metadata_header_remains_accepted(tmp_path):
    _fixture(tmp_path)
    pin = _repin_wheel(tmp_path, _wheel_bytes(folded_license=True))
    assert observe(tmp_path, pin)["status"] == "PASS_PARTIAL"


def test_excess_central_directory_rejected_before_zipfile_allocation(
        tmp_path, monkeypatch):
    _fixture(tmp_path)
    raw = BytesIO()
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_STORED) as archive:
        for i in range(8200):
            archive.writestr(f"synthetic/{i:05d}.txt", b"")
    pin = _repin_wheel(tmp_path, raw.getvalue())
    from tools import sraf_airgap_off2_wheel_files as tool

    def should_not_construct_archive(*args, **kwargs):
        raise AssertionError("ZipFile called before enforcing central-directory member limit")

    monkeypatch.setattr(tool.zipfile, "ZipFile", should_not_construct_archive)
    assert observe(tmp_path, pin) == {
        "status": "INCOMPLETE", "reason": "wheel_archive_structure_invalid",
        "wheels_checked": 1,
    }


def test_forged_eocd_member_count_rejected_before_zipfile(tmp_path, monkeypatch):
    _fixture(tmp_path)
    raw = bytearray(_wheel_bytes())
    pos = raw.rfind(b"PK\x05\x06")
    assert pos != -1
    # EOCD total entries: offset 10. A forged count cannot permit parser allocation.
    import struct
    struct.pack_into("<H", raw, pos + 10, 1)
    pin = _repin_wheel(tmp_path, bytes(raw))
    from tools import sraf_airgap_off2_wheel_files as tool
    monkeypatch.setattr(
        tool.zipfile, "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ZipFile constructor must not run for inconsistent EOCD")
        ),
    )
    assert observe(tmp_path, pin)["reason"] == "wheel_archive_structure_invalid"



@pytest.mark.parametrize("comment", [
    b"archive notes PK\x05\x06 trailing false signature",
    b"archive notes PK\x05\x06" + b"X" * 32,
])
def test_eocd_signature_in_zip_comment_rejected_before_zipfile(
        tmp_path, monkeypatch, comment):
    _fixture(tmp_path)
    content = BytesIO(_wheel_bytes())
    with zipfile.ZipFile(content, "a") as z:
        z.comment = comment
    pin = _repin_wheel(tmp_path, content.getvalue())
    from tools import sraf_airgap_off2_wheel_files as tool

    def refuse_zipfile_allocation(*args, **kwargs):
        raise AssertionError("ambiguous EOCD reached eager ZipInfo constructor")

    monkeypatch.setattr(tool.zipfile, "ZipFile", refuse_zipfile_allocation)
    assert observe(tmp_path, pin) == {
        "status": "INCOMPLETE", "reason": "wheel_archive_structure_invalid",
        "wheels_checked": 1,
    }



@pytest.mark.parametrize("case", [
    "missing_record", "missing_entry", "bad_hash", "bad_size",
    "extra_row", "record_hash",
])
def test_pinned_wheel_record_missing_mismatched_or_uncovered_fails_closed(
        tmp_path, case):
    _fixture(tmp_path)
    pin = _repin_wheel(tmp_path, _wheel_bytes(record_case=case))
    assert observe(tmp_path, pin) == {
        "status": "INCOMPLETE", "reason": "wheel_archive_structure_invalid",
        "wheels_checked": 1,
    }


def test_record_newline_bomb_rejected_before_materializing_rows(tmp_path, monkeypatch):
    _fixture(tmp_path)
    pin = _repin_wheel(tmp_path, _wheel_bytes(record_case="blank_row_bomb"))
    from tools import sraf_airgap_off2_wheel_files as tool
    original = tool.csv.reader
    rows_seen = []

    def guarded_reader(*args, **kwargs):
        for row in original(*args, **kwargs):
            rows_seen.append(1)
            # Eager list(reader) would consume ~2 million records here.
            assert len(rows_seen) <= 2, "RECORD parser iterated beyond fail-fast"
            yield row

    monkeypatch.setattr(tool.csv, "reader", guarded_reader)
    assert observe(tmp_path, pin) == {
        "status": "INCOMPLETE", "reason": "wheel_archive_structure_invalid",
        "wheels_checked": 1,
    }
    assert len(rows_seen) == 1


def test_record_verification_uncompressed_budget_is_fail_closed(tmp_path, monkeypatch):
    _fixture(tmp_path)
    from tools import sraf_airgap_off2_wheel_files as tool
    monkeypatch.setattr(tool, "MAX_RECORD_VERIFY_UNCOMPRESSED_BYTES", 8)
    pin = _repin_wheel(tmp_path, _wheel_bytes())
    assert observe(tmp_path, pin)["reason"] == "wheel_archive_structure_invalid"


def test_record_csv_bad_or_duplicate_path_is_rejected(tmp_path):
    _fixture(tmp_path)
    for case in ("bad_hash", "extra_row", "record_hash"):
        pin = _repin_wheel(tmp_path, _wheel_bytes(record_case=case))
        assert observe(tmp_path, pin)["status"] == "INCOMPLETE"



def test_legacy_signature_sidecar_may_be_omitted_from_record(tmp_path):
    _fixture(tmp_path)
    pin = _repin_wheel(tmp_path, _wheel_bytes(include_legacy_signature=True))
    # Structural acceptance is not trust in the signature's authenticity.
    assert observe(tmp_path, pin)["status"] == "PASS_PARTIAL"


def test_total_decoded_budget_spans_all_wheels(tmp_path, monkeypatch):
    _fixture(tmp_path)
    other = "example_pkg-1.0-py2-none-any.whl"
    data = _wheel_bytes()
    (tmp_path / "wheelhouse" / other).write_bytes(data)
    path = tmp_path / MANIFEST
    payload = json.loads(path.read_text())
    payload["wheels"].append({
        "filename": other, "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    })
    manifest_raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path.write_bytes(manifest_raw)
    pin = hashlib.sha256(manifest_raw).hexdigest()
    with zipfile.ZipFile(BytesIO(data)) as z:
        required_bytes = sum(i.file_size for i in z.infolist()
                             if i.filename != f"{DIST_INFO}/RECORD.jws")
    from tools import sraf_airgap_off2_wheel_files as tool
    monkeypatch.setattr(tool, "MAX_TOTAL_RECORD_VERIFY_UNCOMPRESSED_BYTES",
                        required_bytes + 1)
    assert observe(tmp_path, pin) == {
        "status": "INCOMPLETE", "reason": "wheel_archive_structure_invalid",
        "wheels_checked": 2,
    }


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
