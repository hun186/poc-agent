from pathlib import Path
from types import SimpleNamespace

import pytest

from operator_e2e.requirement_e2e_support import ExitCode, HarnessFailure, result_document
from operator_e2e.test_requirement_schedule_e2e import Api, Harness, main


def _harness(tmp_path, *, remote_timeout=20):
    config = SimpleNamespace(
        output_dir=tmp_path, token="top-secret-token", password="password-secret",
        handoff_timeout_seconds=5, remote_timeout_seconds=remote_timeout,
    )
    return Harness(config, Path("unused.xlsx"), "run", result_document("run"))


def _batch(remote_state="queued", execution_state="pending", *, batch_state="running"):
    return {
        "schedule_id": "schedule-1", "batch_run_id": "batch-1", "state": batch_state,
        "success_count": 3 if batch_state == "completed" else 0, "failure_count": 0,
        "items": [
            {
                "selection_status": "selected", "run_item_id": f"item-{number}",
                "requirement_id": f"requirement-{number}", "remote_job_id": f"job-{number}",
                "dispatched_at": "2026-09-22T00:00:00+00:00",
                "remote_job_state": remote_state, "execution_state": execution_state,
            }
            for number in range(3)
        ],
    }


class _Clock:
    def __init__(self): self.now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


def test_pass_stage_records_evidence_and_logs_redacted_stdout(tmp_path, capsys):
    harness = _harness(tmp_path)

    harness.pass_stage("AUTH", status="ok", credential="Bearer top-secret-token")

    stage = next(item for item in harness.result["stages"] if item["name"] == "AUTH")
    assert stage["status"] == "PASS"
    assert stage["evidence"]["status"] == "ok"
    stdout = capsys.readouterr().out
    assert "PASS AUTH" in stdout and "status=ok" in stdout
    assert "top-secret-token" not in stdout
    assert "<REDACTED>" in stdout


def test_remote_progress_logs_changes_without_poll_spam(tmp_path, monkeypatch, capsys):
    harness = _harness(tmp_path)
    queued = _batch()
    running = _batch("running", "running")
    completed = _batch("completed", "completed", batch_state="completed")
    replies = iter([queued, queued, running, running, completed])
    harness.api = SimpleNamespace(get=lambda *_args, **_kwargs: next(replies))
    clock = _Clock()
    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.time.monotonic", clock.monotonic)
    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.time.sleep", clock.sleep)

    assert harness.wait_terminal(queued)["state"] == "completed"

    stdout = capsys.readouterr().out
    assert "remote_job_state=queued" in stdout
    assert "remote_job_state=running" in stdout
    assert "completed=3/3" in stdout
    # Handoff prints the initial identities once; unchanged remote polls add no ITEM records.
    assert stdout.count("remote_job_state=queued") == 6


def test_remote_heartbeat_and_timeout_final_snapshot_preserve_failure(tmp_path, monkeypatch, capsys):
    harness = _harness(tmp_path, remote_timeout=16)
    batch = _batch("running", "running")
    harness.api = SimpleNamespace(get=lambda *_args, **_kwargs: batch)
    clock = _Clock()
    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.time.monotonic", clock.monotonic)
    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.time.sleep", clock.sleep)

    with pytest.raises(HarnessFailure) as raised:
        harness.wait_terminal(batch)

    assert str(raised.value) == "remote_execution_timeout"
    assert raised.value.stage == "REMOTE_EXECUTION"
    stdout = capsys.readouterr().out
    assert "REMOTE_EXECUTION completed=0/3" in stdout and "heartbeat=True" in stdout
    assert "TIMEOUT REMOTE_EXECUTION" in stdout
    assert stdout.count("remote_job_state=running") >= 6


def test_remote_terminal_failure_logs_final_snapshot_before_raising(tmp_path, monkeypatch, capsys):
    harness = _harness(tmp_path)
    dispatched = _batch("running", "running")
    failed = _batch("failed", "failed", batch_state="failed")
    replies = iter([dispatched, failed])
    harness.api = SimpleNamespace(get=lambda *_args, **_kwargs: next(replies))
    clock = _Clock()
    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.time.monotonic", clock.monotonic)
    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.time.sleep", clock.sleep)

    with pytest.raises(HarnessFailure, match="remote_execution_failed") as raised:
        harness.wait_terminal(dispatched)

    assert raised.value.stage == "REMOTE_EXECUTION"
    stdout = capsys.readouterr().out
    assert "REMOTE_EXECUTION batch_state=failed" in stdout
    assert "ITEM execution_state=failed" in stdout
    assert "remote_job_state=failed" in stdout


def test_final_evidence_pass_is_not_logged_when_summary_write_fails(tmp_path, monkeypatch, capsys):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setenv("SRA_E2E_MODEL", "model")
    monkeypatch.setenv("SRA_E2E_REQUIREMENT_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("SRA_E2E_EDITOR_TOKEN", "test-token")
    monkeypatch.setenv("SRA_E2E_EXPECTED_RUNTIME_SHA", "a" * 40)
    monkeypatch.setattr(
        "operator_e2e.test_requirement_schedule_e2e._provenance_source",
        lambda *_args, **_kwargs: {
            "repository": "hun186/poc-agent", "reviewed_runtime_sha": "a" * 40,
            "provenance_fingerprint": "f" * 64, "identity_verified": True,
        },
    )
    monkeypatch.setattr(Harness, "run", lambda self: None)
    real_write_text = __import__(
        "operator_e2e.test_requirement_schedule_e2e", fromlist=["atomic_write_text"]
    ).atomic_write_text

    def fail_summary(path, value, **kwargs):
        if path.name == "summary.txt":
            raise OSError("simulated summary write failure")
        return real_write_text(path, value, **kwargs)

    monkeypatch.setattr("operator_e2e.test_requirement_schedule_e2e.atomic_write_text", fail_summary)

    code = main([
        "--excel", "unused.xlsx", "--env-file", str(tmp_path / "missing.env"),
        "--output-dir", str(tmp_path / "evidence"),
    ])

    assert code == ExitCode.INTERNAL
    stdout = capsys.readouterr().out
    assert "PASS FINAL_EVIDENCE" not in stdout
    assert "FAILED_STAGE = FINAL_EVIDENCE" in stdout
    assert "FAILURE_CATEGORY = evidence_write_failed" in stdout


def test_manual_run_guard_remains_fail_closed(tmp_path):
    api = Api(SimpleNamespace(base_url="http://unused", token=None))
    with pytest.raises(AssertionError, match="manual run forbidden"):
        api.request_raw("POST", "/v1/requirement-schedules/schedule-1/runs")
