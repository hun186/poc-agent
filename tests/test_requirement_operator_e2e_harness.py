from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SRA_E2E_EXPECTED_SOURCE_SHA", "a" * 40),
        ("SRA_E2E_EXPECTED_RUNTIME_SHA", "a" * 64),
        ("SRA_E2E_EXPECTED_SOURCE_SHA", "z" * 64),
        ("SRA_E2E_EXPECTED_RUNTIME_SHA", "z" * 40),
    ],
)
def test_config_rejects_malformed_source_and_runtime_shas(tmp_path, name, value):
    env = {
        "SRA_E2E_MODEL": "m",
        "SRA_E2E_REQUIREMENT_ARTIFACT_ROOT": str(tmp_path),
        "SRA_E2E_EDITOR_TOKEN": "t",
        name: value,
    }
    with pytest.raises(HarnessFailure, match="configuration_error") as failure:
        E2EConfig.from_environment(env)
    assert failure.value.stage == "CONFIG_PREFLIGHT"


def test_input_sha_validation_and_evidence_are_input_only(tmp_path):
    from operator_e2e.test_requirement_schedule_e2e import Harness

    excel = Path("operator_e2e/input/requirement_e2e_3items.xlsx")
    digest = hashlib.sha256(excel.read_bytes()).hexdigest()
    result = result_document("run")
    config = SimpleNamespace(
        output_dir=tmp_path, token="token", password=None, expected_source_sha=digest,
    )
    harness = Harness(config, excel, "run", result)
    harness.validate_input()
    assert result["input"]["sha256"] == digest
    assert result["input"]["expected_sha256"] == digest

    mismatch = Harness(
        SimpleNamespace(**{**config.__dict__, "expected_source_sha": "0" * 64}),
        excel,
        "run-2",
        result_document("run-2"),
    )
    with pytest.raises(HarnessFailure, match="input_invalid") as failure:
        mismatch.validate_input()
    assert failure.value.stage == "INPUT_VALIDATION"


def test_runtime_source_evidence_uses_only_runtime_sha(monkeypatch):
    from operator_e2e.test_requirement_schedule_e2e import _git_source

    monkeypatch.setenv("SRA_E2E_EXPECTED_SOURCE_SHA", "1" * 64)
    evidence = _git_source("9bf009922d3be304d65d59927f62bbbb3f21e305")
    assert evidence["expected_runtime_sha"] == "9bf009922d3be304d65d59927f62bbbb3f21e305"
    assert evidence["expected_runtime_sha"] != os.environ["SRA_E2E_EXPECTED_SOURCE_SHA"]


def test_runtime_sha_mismatch_fails_before_harness_mutations(tmp_path, monkeypatch):
    from operator_e2e.test_requirement_schedule_e2e import Harness, main

    artifact_root = tmp_path / "artifact-root"
    artifact_root.mkdir()
    env_file = tmp_path / "e2e.env.local"
    env_file.write_text(
        f"SRA_E2E_MODEL=model\nSRA_E2E_REQUIREMENT_ARTIFACT_ROOT={artifact_root}\n"
        f"SRA_E2E_EDITOR_TOKEN=token\nSRA_E2E_EXPECTED_RUNTIME_SHA={'b' * 40}\n",
        encoding="utf-8",
    )
    mutations = []
    monkeypatch.setattr(Harness, "run", lambda self: mutations.append("run"))
    monkeypatch.setattr(
        "operator_e2e.test_requirement_schedule_e2e._git_source",
        lambda expected: {
            "repository": "hun186/poc-agent", "expected_runtime_sha": expected,
            "local_git_sha": "a" * 40, "local_git_dirty": False,
        },
    )

    output = tmp_path / "evidence"
    code = main([
        "--excel", "unused.xlsx", "--env-file", str(env_file), "--output-dir", str(output),
    ])
    assert code == ExitCode.PREFLIGHT
    assert mutations == []
    result = json.loads(next(output.glob("*/result.json")).read_text())
    assert result["failed_stage"] == "CONFIG_PREFLIGHT"
    assert result["failure_category"] == "runtime_source_identity_mismatch"


def test_dirty_reviewed_runtime_fails_before_harness_mutations(tmp_path, monkeypatch):
    from operator_e2e.test_requirement_schedule_e2e import Harness, main

    reviewed_sha = "a" * 40
    artifact_root = tmp_path / "artifact-root"
    artifact_root.mkdir()
    env_file = tmp_path / "e2e.env.local"
    env_file.write_text(
        f"SRA_E2E_MODEL=model\nSRA_E2E_REQUIREMENT_ARTIFACT_ROOT={artifact_root}\n"
        f"SRA_E2E_EDITOR_TOKEN=token\nSRA_E2E_EXPECTED_RUNTIME_SHA={reviewed_sha}\n",
        encoding="utf-8",
    )
    run_calls = []
    monkeypatch.setattr(Harness, "run", lambda self: run_calls.append(self))
    monkeypatch.setattr(
        "operator_e2e.test_requirement_schedule_e2e._git_source",
        lambda expected: {
            "repository": "hun186/poc-agent",
            "expected_runtime_sha": expected,
            "local_git_sha": reviewed_sha,
            "local_git_dirty": True,
        },
    )

    output = tmp_path / "evidence"
    code = main([
        "--excel", "unused.xlsx", "--env-file", str(env_file), "--output-dir", str(output),
    ])

    assert code == ExitCode.PREFLIGHT
    assert len(run_calls) == 0
    result = json.loads(next(output.glob("*/result.json")).read_text())
    assert result["failed_stage"] == "CONFIG_PREFLIGHT"
    assert result["failure_category"] == "runtime_source_dirty"


def test_clean_reviewed_runtime_passes_source_validation():
    from operator_e2e.test_requirement_schedule_e2e import _validate_runtime_source

    reviewed_sha = "a" * 40
    _validate_runtime_source({
        "expected_runtime_sha": reviewed_sha,
        "local_git_sha": reviewed_sha,
        "local_git_dirty": False,
    })


def test_runbook_uses_external_runtime_sha_authority_and_stable_xlsx_digest():
    runbook = Path("docs/operations/requirement-automatic-operator-e2e.md").read_text(
        encoding="utf-8",
    )
    runtime_assignments = re.findall(
        r"^SRA_E2E_EXPECTED_RUNTIME_SHA=(\S+)$", runbook, flags=re.MULTILINE,
    )

    assert runtime_assignments
    assert all(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in runtime_assignments)
    assert "post-merge" in runbook.lower()
    assert "git rev-parse HEAD" in runbook
    assert "repository-self-authoritative" in runbook
    assert "copying an old sha from repository history is invalid" in runbook.lower()
    assert (
        "SRA_E2E_EXPECTED_SOURCE_SHA="
        "2d50bed20a3e697020107ece218e7c001580e1df03adc1c30f8060c4e9118d03"
    ) in runbook


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


def test_disabled_schedule_batch_keeps_polling_identity(monkeypatch, tmp_path):
    from operator_e2e.test_requirement_schedule_e2e import Harness

    schedule_id, batch_id = "schedule-durable", "batch-durable"
    initial = (datetime.now(timezone.utc) + timedelta(seconds=30)).replace(microsecond=0)
    selected = [
        {
            "run_item_id": f"item-{index}", "requirement_id": f"req-{index}",
            "selection_status": "selected", "remote_job_id": f"job-{index}",
            "dispatched_at": initial.isoformat(), "remote_job_state": "completed",
            "execution_state": "completed",
        }
        for index in range(3)
    ]
    batch = {
        "schedule_id": schedule_id, "batch_run_id": batch_id, "trigger_type": "scheduled",
        "schedule_version_id": "version-1", "scheduled_for": initial.isoformat(),
        "snapshot_id": "snapshot-1", "selected_count": 3, "skipped_count": 0,
        "success_count": 3, "failure_count": 0, "state": "completed", "items": selected,
    }

    class FakeApi:
        def __init__(self): self.poll_paths, self.enabled = [], False
        def get(self, path, **_kwargs):
            if path == f"/v1/requirement-schedules/{schedule_id}/runs?limit=100":
                return {"items": [{"batch_run_id": batch_id}]} if self.enabled else {"items": []}
            if path == f"/v1/requirement-schedules/{schedule_id}":
                return {"versions": [], "next_run_at": (initial + timedelta(days=7)).isoformat()}
            if path == f"/v1/requirement-schedules/{schedule_id}/runs/{batch_id}":
                self.poll_paths.append(path); return batch
            raise AssertionError(path)
        def post(self, path, **_kwargs):
            if path.endswith("/versions"): return {"schedule_version_id": "version-1", "version_number": 1}
            if path.endswith("/approve"): return {}
            raise AssertionError(path)
        def patch(self, path, *, json, **_kwargs):
            assert path == f"/v1/requirement-schedules/{schedule_id}"
            if json["enabled"]:
                self.enabled = True
                return {"enabled": True, "active_version_id": "version-1", "next_run_at": initial.isoformat()}
            return {"enabled": False}

    config = SimpleNamespace(anchor_lead_seconds=30, allowed_anchor_window_seconds=60,
                             auto_claim_timeout_seconds=1, handoff_timeout_seconds=1,
                             remote_timeout_seconds=1, model="model", output_dir=tmp_path,
                             token="token", password=None)
    result = result_document("run")
    harness = Harness(config, tmp_path / "unused.xlsx", "run", result)
    harness.api = FakeApi()
    detail = harness.schedule_and_wait({"schedule_id": schedule_id}, "snapshot-1", {f"req-{i}" for i in range(3)})

    assert harness.enabled_schedule_id is None
    assert harness.wait_terminal(detail)["batch_run_id"] == batch_id
    assert harness.api.poll_paths and set(harness.api.poll_paths) == {f"/v1/requirement-schedules/{schedule_id}/runs/{batch_id}"}


def test_env_file_output_directory_is_authoritative_for_all_evidence(tmp_path, monkeypatch):
    from operator_e2e.test_requirement_schedule_e2e import Harness, main

    for key in tuple(os.environ):
        if key.startswith("SRA_E2E_"): monkeypatch.delenv(key, raising=False)
    artifact_root = tmp_path / "artifact-root"; artifact_root.mkdir()
    output = tmp_path / "env-output"
    env_file = tmp_path / "e2e.env.local"
    env_file.write_text(
        f"SRA_E2E_MODEL=model\nSRA_E2E_REQUIREMENT_ARTIFACT_ROOT={artifact_root}\n"
        f"SRA_E2E_EDITOR_TOKEN=token\nSRA_E2E_OUTPUT_DIR={output}\n", encoding="utf-8",
    )
    observed = {}
    monkeypatch.setattr(Harness, "run", lambda self: observed.update(output=self.output, config=self.config.output_dir))

    assert main(["--excel", "unused.xlsx", "--env-file", str(env_file)]) == ExitCode.PASS
    runs = list(output.iterdir())
    assert observed["config"] == output and observed["output"].parent == output
    assert len([path for path in runs if path.is_dir()]) == 1
    assert {path.name for path in observed["output"].iterdir()} == {"result.json", "summary.txt", "diagnostics.json", "artifacts"}
    assert (output / ".lock").exists()


def test_import_ambiguous_write_ignores_historical_matching_snapshots(tmp_path):
    import requests
    from operator_e2e.test_requirement_schedule_e2e import Harness

    old_ids = {"historical-1", "historical-2", "active-before"}
    new_id = "new-snapshot"

    class FakeApi:
        imported = False
        import_post_count = 0
        def post(self, path, **_kwargs):
            if path.endswith("/preview") or "/preview?" in path:
                return {"has_errors": False, "accepted_count": 3, "rejected_count": 0, "source_sha256": "same-sha"}
            if path.endswith("/import"):
                self.import_post_count += 1
                self.imported = True; raise requests.Timeout()
            raise AssertionError(path)
        def get(self, path, **_kwargs):
            if path == "/v1/requirement-sets":
                active = new_id if self.imported else "active-before"
                return {"items": [{"source_id": "source-1", "requirement_set_id": "set-1", "active_snapshot_id": active}]}
            if path == "/v1/requirement-sets/set-1/snapshots":
                ids = old_ids | ({new_id} if self.imported else set())
                return {"items": [
                    {
                        "snapshot_id": sid,
                        "requirement_set_id": "set-1",
                        "import_run_id": "new-import-run" if sid == new_id else f"import-{sid}",
                        "source_snapshot_sha256": "same-sha",
                        "import_profile_version_id": "profile-v1",
                        "created_at": "2026-09-15T00:00:00+00:00",
                        "activated_at": "2026-09-15T00:00:00+00:00",
                    }
                    for sid in sorted(ids)
                ]}
            if path == f"/v1/requirement-snapshots/{new_id}/items":
                return {"items": [{"requirement_id": f"req-{i}", "expires_at": None} for i in range(3)]}
            raise AssertionError(path)

    excel = tmp_path / "input.xlsx"; excel.write_bytes(b"xlsx")
    config = SimpleNamespace(output_dir=tmp_path, token="token", password=None)
    harness = Harness(config, excel, "run", result_document("run")); harness.api = FakeApi()
    reqset, items = harness.import_requirements({"source_id": "source-1"}, {"profile_version_id": "profile-v1"})
    assert reqset["active_snapshot_id"] == new_id
    assert harness.result["requirement_import"]["snapshot_id"] == new_id
    assert harness.result["requirement_import"]["import_run_id"] == "new-import-run"
    assert harness.api.import_post_count == 1
    assert len(items) == 3
