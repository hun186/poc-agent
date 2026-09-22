from pathlib import Path
from types import SimpleNamespace

import pytest

from operator_e2e.requirement_e2e_support import HarnessFailure, result_document
from operator_e2e.test_requirement_schedule_e2e import Api, Harness


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


def test_manual_run_guard_remains_fail_closed(tmp_path):
    api = Api(SimpleNamespace(base_url="http://unused", token=None))
    with pytest.raises(AssertionError, match="manual run forbidden"):
        api.request_raw("POST", "/v1/requirement-schedules/schedule-1/runs")
