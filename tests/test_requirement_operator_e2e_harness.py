from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook

from operator_e2e.requirement_e2e_support import (
    E2EConfig,
    ExitCode,
    HarnessFailure,
    StageStatus,
    atomic_write_json,
    bounded_log_tail,
    choose_fixture,
    classify_new_batch,
    load_e2e_environment,
    recover_ambiguous_write,
    redact,
    result_document,
    validate_artifact,
    validate_next_run,
    validate_preview,
    validate_remote_items,
    validate_terminal,
    verify_worker_identity,
)


def test_env_contract_rejects_foreign_key_and_process_env_wins(tmp_path, monkeypatch):
    env_file = tmp_path / "e2e.env.local"
    env_file.write_text("OTHER=x\nSRA_E2E_MODEL=file\n", encoding="utf-8")
    with pytest.raises(HarnessFailure, match="configuration_error"):
        load_e2e_environment(env_file, {})
    env_file.write_text("SRA_E2E_MODEL=file\n", encoding="utf-8")
    assert load_e2e_environment(env_file, {"SRA_E2E_MODEL": "process"})["SRA_E2E_MODEL"] == "process"


def test_config_auth_and_required_values(tmp_path):
    base = {"SRA_E2E_MODEL": "m", "SRA_E2E_REQUIREMENT_ARTIFACT_ROOT": str(tmp_path)}
    with pytest.raises(HarnessFailure):
        E2EConfig.from_environment(base)
    with pytest.raises(HarnessFailure):
        E2EConfig.from_environment({**base, "SRA_E2E_EDITOR_TOKEN": "t", "SRA_E2E_EDITOR_USERNAME": "u", "SRA_E2E_EDITOR_PASSWORD": "p"})
    config = E2EConfig.from_environment({**base, "SRA_E2E_EDITOR_TOKEN": "t"})
    assert config.model == "m" and config.exit_code_for_failure == ExitCode.PREFLIGHT


def test_redaction_removes_headers_fields_and_known_literals():
    secret = "SENTINEL-SECRET"
    value = {"Authorization": f"Bearer {secret}", "nested": f"password={secret} token={secret} PWD={secret} User ID=bob"}
    encoded = json.dumps(redact(value, [secret]))
    assert secret not in encoded and "bob" not in encoded and encoded.count("REDACTED") >= 2


def test_result_schema_and_atomic_evidence_does_not_overwrite(tmp_path):
    doc = result_document("run-1")
    assert doc["schema_version"] == "requirement_e2e_result_v1"
    assert all(stage["status"] == StageStatus.NOT_REACHED for stage in doc["stages"])
    target = tmp_path / "result.json"
    atomic_write_json(target, doc)
    with pytest.raises(FileExistsError):
        atomic_write_json(target, doc)


@pytest.mark.parametrize("items,expected", [([], "create"), ([{"fingerprint": "x"}], "reuse")])
def test_fixture_create_and_reuse(items, expected):
    assert choose_fixture(items, lambda item: item["fingerprint"] == "x")[0] == expected


def test_fixture_drift_and_ambiguity_fail_closed():
    with pytest.raises(HarnessFailure, match="fixture_drift"):
        choose_fixture([{"fingerprint": "bad"}], lambda item: item["fingerprint"] == "x")
    with pytest.raises(HarnessFailure, match="fixture_ambiguous"):
        choose_fixture([{"fingerprint": "x"}, {"fingerprint": "x"}], lambda item: True)


def test_ambiguous_write_rereads_before_retry():
    assert recover_ambiguous_write(lambda: [{"id": "winner"}]) == {"id": "winner"}
    assert recover_ambiguous_write(lambda: []) is None
    with pytest.raises(HarnessFailure, match="ambiguous_write"):
        recover_ambiguous_write(lambda: [{"id": "a"}, {"id": "b"}])


def test_preview_requires_exactly_three():
    validate_preview({"has_errors": False, "accepted_count": 3, "rejected_count": 0})
    with pytest.raises(HarnessFailure, match="preview_rejected"):
        validate_preview({"has_errors": False, "accepted_count": 2, "rejected_count": 0})


def _batch(**changes):
    value = {"batch_run_id": "b", "trigger_type": "scheduled", "schedule_version_id": "v", "scheduled_for": "2026-01-01T00:00:00+00:00", "snapshot_id": "s", "selected_count": 3, "skipped_count": 0}
    value.update(changes)
    return value


def test_automatic_batch_identity_and_rejections():
    assert classify_new_batch([_batch()], set(), "v", "s", "2026-01-01T00:00:00+00:00")["batch_run_id"] == "b"
    with pytest.raises(HarnessFailure, match="snapshot_identity_mismatch"):
        classify_new_batch([_batch(snapshot_id="wrong")], set(), "v", "s", "2026-01-01T00:00:00+00:00")
    with pytest.raises(HarnessFailure, match="multiple_scheduled_runs"):
        classify_new_batch([_batch(batch_run_id="a"), _batch(batch_run_id="b")], set(), "v", "s", "2026-01-01T00:00:00+00:00")


def test_remote_job_and_terminal_validation():
    items = [{"selection_status": "selected", "remote_job_id": f"j{i}", "remote_job_state": "completed", "execution_state": "completed"} for i in range(3)]
    validate_remote_items(items)
    validate_terminal({"state": "completed", "success_count": 3, "failure_count": 0, "items": items})
    items[2]["remote_job_id"] = "j1"
    with pytest.raises(HarnessFailure, match="remote_job_count_mismatch"):
        validate_remote_items(items)
    items[2].update(remote_job_id="j2", remote_job_state="failed")
    with pytest.raises(HarnessFailure, match="remote_execution_failed"):
        validate_terminal({"state": "running", "success_count": 2, "failure_count": 1, "items": items})


def _docx(path: Path, member="word/document.xml"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(member, "<document/>")


def test_artifact_fingerprint_docx_and_sha(tmp_path):
    root = tmp_path / "root"; root.mkdir(); path = root / "a.docx"; _docx(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    copied = tmp_path / "copy.docx"
    evidence = validate_artifact(root, hashlib.sha256(str(root.resolve()).encode()).hexdigest(), "a.docx", digest, copied)
    assert evidence["actual_sha256"] == digest and copied.read_bytes() == path.read_bytes()
    with pytest.raises(HarnessFailure, match="artifact_sha256_mismatch"):
        validate_artifact(root, hashlib.sha256(str(root.resolve()).encode()).hexdigest(), "a.docx", "0" * 64, tmp_path / "bad.docx")
    evil = root / "evil.docx"; _docx(evil, "../evil")
    with pytest.raises(HarnessFailure, match="artifact_invalid"):
        validate_artifact(root, hashlib.sha256(str(root.resolve()).encode()).hexdigest(), "evil.docx", hashlib.sha256(evil.read_bytes()).hexdigest(), tmp_path / "evil-copy.docx")


def test_worker_identity_verification(tmp_path, monkeypatch):
    identity = tmp_path / "identity"
    identity.write_text(f"role=schedule\npid={os.getpid()}\nprocess_start_time=123\n", encoding="utf-8")
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_start_time", lambda pid: "123")
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_uid", lambda pid: os.geteuid())
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_cwd", lambda pid: tmp_path.resolve())
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_cmdline", lambda pid: "python -m requirement_scheduler.cli schedule-worker")
    assert verify_worker_identity(identity, "schedule", tmp_path)["alive"] is True
    identity.write_text(f"role=schedule\npid={os.getpid()}\nprocess_start_time=999\n", encoding="utf-8")
    with pytest.raises(HarnessFailure, match="worker_unavailable"):
        verify_worker_identity(identity, "schedule", tmp_path)


def test_worker_identity_rejects_wrong_command_and_cwd(tmp_path, monkeypatch):
    identity = tmp_path / "identity"
    identity.write_text(f"role=handoff\npid={os.getpid()}\nprocess_start_time=123\n", encoding="utf-8")
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_start_time", lambda pid: "123")
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_uid", lambda pid: os.geteuid())
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_cwd", lambda pid: tmp_path.resolve())
    monkeypatch.setattr("operator_e2e.requirement_e2e_support._proc_cmdline", lambda pid: "python unrelated.py")
    with pytest.raises(HarnessFailure, match="worker_unavailable"):
        verify_worker_identity(identity, "handoff", tmp_path)


def test_bounded_log_tail_is_capped_and_redacted(tmp_path):
    secret = "SENTINEL-LOG-SECRET"
    path = tmp_path / "worker.log"
    path.write_text("\n".join(["old"] * 120 + [f"Authorization: Bearer {secret}", f"password={secret}"]), encoding="utf-8")
    tail = bounded_log_tail(path, [secret], max_lines=3, max_bytes=65536)
    assert secret not in tail and len(tail.splitlines()) == 3


def test_next_run_advancement_contract():
    scheduled_for = datetime(2026, 1, 1, tzinfo=timezone.utc)
    validate_next_run(scheduled_for, datetime(2026, 1, 8, tzinfo=timezone.utc))
    with pytest.raises(HarnessFailure, match="automatic_claim_identity_mismatch"):
        validate_next_run(scheduled_for, scheduled_for + timedelta(minutes=1))


def test_exit_codes_are_stable():
    assert tuple(int(code) for code in ExitCode) == (0, 2, 3, 4, 5)


def test_entrypoint_contains_no_manual_run_or_worker_execution():
    source = Path("operator_e2e/test_requirement_schedule_e2e.py").read_text(encoding="utf-8")
    assert 'post(f"/v1/requirement-schedules/{schedule_id}/runs"' not in source.lower()
    assert "schedule-worker --once" not in source
    assert "coordinator.run_once" not in source


def test_tracked_xlsx_fixture_has_canonical_three_item_shape():
    path = Path("operator_e2e/input/requirement_e2e_3items.xlsx")
    book = load_workbook(path, read_only=True)
    rows = list(book.active.iter_rows(values_only=True)); book.close()
    assert rows[0] == ("external_item_id", "title", "prompt_content", "source_updated_at", "source_created_at", "expires_at")
    assert len(rows[1:]) == 3


def test_config_failure_still_writes_safe_evidence(tmp_path, monkeypatch):
    from operator_e2e.test_requirement_schedule_e2e import main
    for key in tuple(os.environ):
        if key.startswith("SRA_E2E_"): monkeypatch.delenv(key, raising=False)
    output = tmp_path / "evidence"
    code = main(["--excel", "missing.xlsx", "--env-file", str(tmp_path / "missing.env"), "--output-dir", str(output)])
    assert code == ExitCode.PREFLIGHT
    runs = list(output.iterdir())
    assert len(runs) == 1
    assert {item.name for item in runs[0].iterdir()} == {"result.json", "summary.txt", "diagnostics.json", "artifacts"}


def test_cleanup_failure_forces_exit_five_and_evidence(tmp_path, monkeypatch):
    from operator_e2e.test_requirement_schedule_e2e import Harness, main
    artifact_root = tmp_path / "artifacts-root"; artifact_root.mkdir()
    monkeypatch.setenv("SRA_E2E_MODEL", "model")
    monkeypatch.setenv("SRA_E2E_REQUIREMENT_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("SRA_E2E_EDITOR_TOKEN", "SENTINEL-TOKEN")
    monkeypatch.setattr(Harness, "run", lambda self: setattr(self, "enabled_schedule_id", "schedule-1"))
    monkeypatch.setattr(Harness, "cleanup", lambda self: (_ for _ in ()).throw(RuntimeError("disable failed")))
    output = tmp_path / "evidence"
    code = main(["--excel", "unused.xlsx", "--env-file", str(tmp_path / "missing.env"), "--output-dir", str(output)])
    assert code == ExitCode.CLEANUP
    result = json.loads(next(output.glob("*/result.json")).read_text())
    assert result["failure_category"] == "cleanup_failed"
    assert "SENTINEL-TOKEN" not in json.dumps(result)
