"""OFF-1P: actual local DOCX bytes, path containment, and SQL gating."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from tools import sraf_airgap_off1p_docx_integrity as docx
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "a" * 32
ITEM = "rit_" + "a" * 32
SECRET = "UNPRINTABLE_PASSWORD"


def cfg():
    return {"SRAF_OFF1G_SQL_HOST": "10.2.3.4", "SRAF_OFF1G_SQL_PORT": "1433",
            "SRAF_OFF1G_SQL_DATABASE": "control", "SRAF_OFF1G_SQL_USER": "readonly",
            "SRAF_OFF1G_SQL_PASSWORD": SECRET}


def payload():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<document><p>report</p></document>")
    return bio.getvalue()


class Cursor:
    def __init__(self, rows, calls):
        self.rows, self.calls = list(rows), calls

    def execute(self, sql, *params):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "requirement_batch_run_items" in sql
        assert "requirement_handoff_submissions" in sql
        assert "i.execution_state=N'completed'" in sql
        assert "r.created_by=N'requirement-schedule-worker'" in sql
        assert "UPDATE " not in sql and "INSERT " not in sql
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class DB:
    def __init__(self, rows, calls):
        self.cur, self.timeout = Cursor(rows, calls), None

    def cursor(self):
        return self.cur

    def close(self):
        pass


def mock_sql(monkeypatch, rows):
    calls = []
    monkeypatch.setattr(docx.pyodbc, "drivers", lambda: [docx.DRIVER])
    monkeypatch.setattr(docx.pyodbc, "connect", lambda *a, **kw: DB(rows, calls))
    return calls


def setup(tmp_path, monkeypatch, *, data=None, expected=None):
    root = tmp_path / "outputs"
    (root / ITEM).mkdir(parents=True)
    bits = data if data is not None else payload()
    (root / ITEM / "summary.docx").write_bytes(bits)
    digest = expected if expected is not None else hashlib.sha256(bits).hexdigest()
    mock_sql(monkeypatch, [(ITEM, ITEM+"/summary.docx", digest,
                             docx.output_root_fingerprint(root))])
    return root


def test_real_docx_bytes_confirmed_but_not_remote_execution(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    o = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID,
                                        artifact_root=str(root))
    assert (o.status, o.reason, o.evidence) == ("PASS", "docx_local_bytes_match",
                                                {"local_docx_byte_match": True})
    assert SECRET not in json.dumps(o.__dict__)
    assert SID not in json.dumps(o.__dict__)
    assert str(root) not in json.dumps(o.__dict__)


def test_actual_digest_mismatch_is_fail(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch, expected="0" * 64)
    o = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert (o.status, o.reason) == ("FAIL", "docx_digest_mismatch")


def test_matching_hash_but_invalid_docx_is_fail(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch, data=b"fake-docx")
    o = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert (o.status, o.reason) == ("FAIL", "docx_structure_invalid")


def test_symlink_filename_is_never_read(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    good = root / ITEM / "summary.docx"
    good.unlink()
    good.symlink_to(tmp_path / "sensitive.outside")
    r = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert (r.status, r.reason) == ("SKIP", "docx_file_unverified")


def test_symlink_directory_is_never_read(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    (root / ITEM / "summary.docx").unlink()
    (root / ITEM).rmdir()
    (root / ITEM).symlink_to(tmp_path)
    r = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert (r.status, r.reason) == ("SKIP", "docx_file_unverified")


@pytest.mark.parametrize("relative", [
    "../sensitive.docx", "/tmp/secrets.docx", ITEM + "/../../abc.docx",
    "someoneelse/report.docx", ITEM + "/abc.txt", ITEM+"\\secret.docx",
])
def test_untrusted_sql_relative_path_rejected(tmp_path, monkeypatch, relative):
    root = setup(tmp_path, monkeypatch)
    mock_sql(monkeypatch, [(ITEM, relative, "a"*64,
                             docx.output_root_fingerprint(root))])
    r = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert r.status == "SKIP"


def test_wrong_root_fingerprint_skips(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    mock_sql(monkeypatch, [(ITEM, ITEM + "/summary.docx", "a" * 64, "b" * 64)])
    r = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert r.reason == "docx_root_mismatch"


def test_wrong_row_and_sql_error_redacted(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    for rows, why in [([], "docx_reference_absent"),
                      ([(ITEM,)], "docx_reference_invalid"),
                      ([(ITEM,ITEM+"/summary.docx","a"*64,"b"*64)]*2,
                       "docx_reference_ambiguous")]:
        mock_sql(monkeypatch, rows)
        assert docx.probe_docx_byte_integrity(cfg(), schedule_id=SID,
            artifact_root=str(root)).reason == why
    monkeypatch.setattr(docx.pyodbc, "connect",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(SECRET)))
    r = docx.probe_docx_byte_integrity(cfg(), schedule_id=SID, artifact_root=str(root))
    assert r.reason == "docx_reference_sql_unverified" and SECRET not in json.dumps(r.__dict__)


def test_invalid_selector_never_contacts_sql(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(docx.pyodbc, "connect", lambda *a,**k: pytest.fail("sql"))
    for sid in (None, "bad-id", SID+";DROP"):
        assert docx.probe_docx_byte_integrity(cfg(),schedule_id=sid,artifact_root=str(root)).status == "SKIP"
    assert docx.probe_docx_byte_integrity(cfg(),schedule_id=SID,artifact_root="../bad").reason == "docx_root_invalid"


@pytest.mark.parametrize("flags,checkpoint,expected", [
    ((False,)*8, "PASS", "NOT_TESTED"),
    ((True,)*7+(False,), "PASS", "NOT_TESTED"),
    ((True,)*8, "SKIP", "SKIP"),
    ((True,)*8, "PASS", "PASS"),
])
def test_matrix_requires_eight_optins_and_prior_checkpoint(monkeypatch, flags, checkpoint, expected):
    calls = []
    def provider(*args,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(check_id="DOCX-BYTES-01",
           probe="docx-byte-integrity",
           aspect="one_persisted_item_local_docx_byte_match_only",
           status="PASS", reason="docx_local_bytes_match", executed=True,
           evidence={"local_docx_byte_match": True})
    monkeypatch.setattr(matrix, "probe_docx_byte_integrity", provider)
    row = matrix._docx_byte_check(
        probe_network=flags[0],probe_sql_read=flags[1],
        probe_worker_identities=flags[2],probe_schedule_claim=flags[3],
        probe_schedule_link=flags[4],probe_handoff_ack=flags[5],
        probe_report_checkpoint=flags[6],probe_docx_bytes=flags[7],
        checkpoint_status=checkpoint,sql_config=cfg(),schedule_id=SID,
        lease_schema=None,artifact_root="/tmp/allowed")
    assert row["status"] == expected
    assert bool(calls) == (expected == "PASS")
    assert row["depends_on"] == ["SQL-READ", "REPORT-CHECKPOINT"]


def test_matrix_rejects_forged_positive(monkeypatch):
    monkeypatch.setattr(matrix, "probe_docx_byte_integrity",lambda *a,**k:
        SimpleNamespace(check_id="DOCX-BYTES-01", probe="docx-byte-integrity",
        aspect="one_persisted_item_local_docx_byte_match_only",status="PASS",
        reason="docx_local_bytes_match",executed=False,
        evidence={"local_docx_byte_match":True,"secret":SECRET}))
    row=matrix._docx_byte_check(probe_network=True,probe_sql_read=True,
        probe_worker_identities=True,probe_schedule_claim=True,
        probe_schedule_link=True,probe_handoff_ack=True,
        probe_report_checkpoint=True,probe_docx_bytes=True,
        checkpoint_status="PASS",sql_config=cfg(),schedule_id=SID,
        lease_schema=None,artifact_root="/tmp/allowed")
    assert row["status"] == "SKIP" and row["reason"] == "unexpected_probe_result"
    assert SECRET not in json.dumps(row)
