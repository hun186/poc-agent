"""OFF-1V only handles synthetic, local JSON snapshots; no live API or provider."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools import sraf_linux_load_compare_offline as cli
from tools.sraf_linux_load_topology_readonly import SCHEMA as SOURCE_SCHEMA


def snapshot(*, rss=(200.0, 201.0, 202.0), threads=(5, 6, 5)):
    return {
        "schema": SOURCE_SCHEMA, "mode": "PARTIAL_ONLY_NOT_ACCEPTANCE",
        "feature_acceptance": "NOT_TESTED", "overall": "PARTIAL_OBSERVATION",
        "checks": {
            "API-LISTENER": {"status": "OBSERVED", "reason": "listener_identity_observed"},
            "API-MOUNT-NAMESPACE": {
                "status": "OBSERVED", "reason": "same_namespace_as_operator_only"},
            "LOCAL-LOCK-CANDIDATE": {
                "status": "SKIP", "reason": "local_lock_candidate_missing"},
            "API-PROCESS-SAMPLES": {
                "status": "OBSERVED", "reason": "process_samples_collected"},
            "CROSS-WORKER-LOCK-SHARING": {
                "status": "NOT_TESTED", "reason": "cannot_prove_from_external_snapshot"},
            "OLLAMA-ES-TIMEOUT": {
                "status": "NOT_TESTED", "reason": "no_model_or_es_request"},
        },
        "samples": [{"sample": i + 1, "rss_mib": value, "threads": threads[i]}
                    for i, value in enumerate(rss)],
        "network_requests": 0, "credentials_sent": False,
        "database_queries": 0, "model_inferences": 0, "mutations": 0,
        "processes_spawned": 0,
    }


def test_bounded_descriptive_comparison_never_promotes_live_acceptance():
    result = cli.compare(
        snapshot(),
        snapshot(rss=(300.0, 301.0, 302.0), threads=(9, 11, 10)),
    )
    assert result["overall"] == "DESCRIPTIVE_COMPARISON"
    assert result["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert result["feature_acceptance"] == "NOT_TESTED"
    assert result["comparability"] == "UNVERIFIED_CROSS_RUN_IDENTITY"
    assert result["cross_worker_lock_sharing"] == "NOT_TESTED"
    assert result["ollama_es_timeout"] == "NOT_TESTED"
    assert result["comparison"] == {
        "sample_count_each": 3, "idle_mean_rss_mib": 201.0,
        "busy_mean_rss_mib": 301.0, "mean_rss_delta_mib": 100.0,
        "mean_rss_delta_percent": 49.75,
        "idle_peak_threads": 6, "busy_peak_threads": 11,
        "peak_threads_delta": 5,
    }
    assert all(result[x] == 0 for x in
               ("network_requests", "model_inferences", "database_queries", "mutations"))
    assert result["credentials_sent"] is False
    assert not any(x in json.dumps(result) for x in
                   ("Bearer", "hostname", "/home/private", "PID:", "FULL_LIVE"))


def test_mismatched_sample_count_returns_incomplete_without_metrics():
    left = snapshot()
    right = snapshot(rss=(1.0, 2.0), threads=(2, 2))
    result = cli.compare(left, right)
    assert result["overall"] == "INCOMPLETE"
    assert result["reason"] == "sample_count_mismatch"
    assert result["comparison"] is None


@pytest.mark.parametrize("patch", [
    lambda x: x.update({"schema": "other"}),
    lambda x: x.update({"overall": "PASS"}),
    lambda x: x.update({"mode": "FULL_LIVE"}),
    lambda x: x.update({"feature_acceptance": "PASS"}),
    lambda x: x.update({"model_inferences": True}),
    lambda x: x.update({"network_requests": 1}),
    lambda x: x.update({"credentials_sent": 0}),
    lambda x: x.update({"extra_secret": "Bearer TOPSECRET"}),
    lambda x: x["checks"].pop("OLLAMA-ES-TIMEOUT"),
    lambda x: x["checks"]["OLLAMA-ES-TIMEOUT"].update({"status": "PASS"}),
    lambda x: x["checks"]["CROSS-WORKER-LOCK-SHARING"].update({"status": "PASS"}),
    lambda x: x["checks"]["API-LISTENER"].update({"status": "SKIP"}),
    lambda x: x["checks"]["API-MOUNT-NAMESPACE"].update({"reason": "forged evidence"}),
    lambda x: x["checks"]["LOCAL-LOCK-CANDIDATE"].update({"reason": "/etc/secrets"}),
    lambda x: x["samples"][0].update({"sample": 3}),
    lambda x: x["samples"][0].update({"rss_mib": float("inf")}),
    lambda x: x["samples"][0].update({"rss_mib": float("nan")}),
    lambda x: x["samples"][0].update({"rss_mib": -1}),
    lambda x: x["samples"][0].update({"threads": True}),
    lambda x: x["samples"][0].update({"threads": 0}),
    lambda x: x["samples"][0].update({"threads": 200000}),
    lambda x: x.update({"samples": []}),
])
def test_invalid_or_misleading_snapshot_never_produces_statistics(patch):
    invalid = snapshot()
    patch(invalid)
    result = cli.compare(snapshot(), invalid)
    assert result["overall"] == "INCOMPLETE"
    assert result["comparison"] is None
    assert result["feature_acceptance"] == "NOT_TESTED"


def test_missing_corrupt_or_unsafe_input_never_exposes_path(tmp_path, capsys):
    missing = tmp_path / "SECRET-access_token=hidden.json"
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(snapshot()), encoding="utf-8")
    assert cli.main(["--idle-file", str(missing), "--busy-file", str(valid)]) == 2
    raw = capsys.readouterr()
    assert "SECRET" not in raw.out + raw.err
    assert "token" not in raw.out + raw.err
    assert json.loads(raw.out)["comparison"] is None


def test_valid_cli_from_regular_json_files(tmp_path, capsys):
    left, right = tmp_path / "idle.json", tmp_path / "busy.json"
    left.write_text(json.dumps(snapshot()), encoding="utf-8")
    right.write_text(json.dumps(snapshot(rss=(220, 221, 222))), encoding="utf-8")
    assert cli.main(["--idle-file", str(left), "--busy-file", str(right)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["overall"] == "DESCRIPTIVE_COMPARISON"
    assert result["comparison"]["mean_rss_delta_mib"] == 20.0


def test_input_symlink_is_never_followed(tmp_path):
    target = tmp_path / "sensitive.json"
    target.write_text(json.dumps(snapshot()), encoding="utf-8")
    link = tmp_path / "alias.json"
    link.symlink_to(target)
    with pytest.raises(cli.ComparisonInputError, match="snapshot_invalid"):
        cli._read_existing_json(link)


def test_oversized_input_is_rejected_without_payload_read(tmp_path):
    target = tmp_path / "oversized.json"
    target.write_bytes(b"X" * (cli.MAX_JSON_BYTES + 1))
    with pytest.raises(cli.ComparisonInputError, match="snapshot_invalid"):
        cli._read_existing_json(target)


@pytest.mark.parametrize("text", [
    '{"schema":"x","schema":"other"}',
    '{"secret":NaN}',
    '{"secret":Infinity}',
    '{"secret":-Infinity}',
    '{"secret":"unterminated"',
    "\xff",
])
def test_invalid_or_ambiguous_json_is_rejected(tmp_path, text):
    target = tmp_path / "input.json"
    if text == "\xff":
        target.write_bytes(b"\xff")
    else:
        target.write_text(text, encoding="utf-8")
    with pytest.raises(cli.ComparisonInputError, match="snapshot_invalid"):
        cli._read_existing_json(target)


def test_incomplete_off1u_output_cannot_be_upgraded():
    left = snapshot()
    left["overall"] = "INCOMPLETE"
    left["samples"] = []
    assert cli.compare(left, snapshot())["overall"] == "INCOMPLETE"


def test_two_snapshots_with_different_context_remain_unverified_identity():
    right = snapshot()
    right["checks"]["API-MOUNT-NAMESPACE"] = {
        "status": "SKIP", "reason": "different_mount_namespace",
    }
    result = cli.compare(snapshot(), right)
    assert result["comparability"] == "UNVERIFIED_CROSS_RUN_IDENTITY"
    assert result["overall"] == "DESCRIPTIVE_COMPARISON"
    assert result["feature_acceptance"] == "NOT_TESTED"


def test_documented_direct_script_help_runs_without_pythonpath(tmp_path):
    """The operator runs python tools/file.py, not python -m tools.file."""
    import os
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[1] / "tools" / "sraf_linux_load_compare_offline.py"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path, env=env, timeout=15, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--idle-file" in result.stdout and "--busy-file" in result.stdout


def test_oversized_rss_integer_fail_closed_in_compare_and_cli(tmp_path, capsys):
    poisoned = snapshot()
    poisoned["samples"][0]["rss_mib"] = 10**400
    assert cli.compare(snapshot(), poisoned)["overall"] == "INCOMPLETE"
    idle = tmp_path / "idle.json"
    busy = tmp_path / "busy.json"
    idle.write_text(json.dumps(snapshot()), encoding="utf-8")
    busy.write_text(json.dumps(poisoned), encoding="utf-8")
    assert cli.main(["--idle-file", str(idle), "--busy-file", str(busy)]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    parsed = json.loads(output.out)
    assert parsed["overall"] == "INCOMPLETE" and parsed["comparison"] is None
    assert str(10**400) not in output.out


def test_deeply_nested_json_returns_sanitized_incomplete(tmp_path, capsys):
    path = tmp_path / "deep-secret.json"
    path.write_text("[" * 1500 + "0" + "]" * 1500, encoding="utf-8")
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(snapshot()), encoding="utf-8")
    assert cli.main(["--idle-file", str(path), "--busy-file", str(valid)]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["overall"] == "INCOMPLETE"
    assert str(path) not in captured.out


def nonexclusive_snapshot():
    value = snapshot()
    value["checks"]["API-LISTENER"] = {
        "status": "OBSERVED", "reason": "launcher_listener_for_local_sampling_only"}
    value["checks"]["SOCKET-EXCLUSIVITY"] = {
        "status": "NOT_TESTED", "reason": "global_fd_scan_intentionally_not_run"}
    return value


def test_off1v_accepts_new_nonexclusive_local_sampling_with_no_promotion():
    result = cli.compare(nonexclusive_snapshot(), nonexclusive_snapshot())
    assert result["overall"] == "DESCRIPTIVE_COMPARISON"
    assert result["feature_acceptance"] == "NOT_TESTED"
    assert result["comparability"] == "UNVERIFIED_CROSS_RUN_IDENTITY"
    assert result["cross_worker_lock_sharing"] == "NOT_TESTED"
    assert result["ollama_es_timeout"] == "NOT_TESTED"


def test_off1v_permits_legacy_and_nonexclusive_inputs_without_claiming_same_authority():
    result = cli.compare(snapshot(), nonexclusive_snapshot())
    assert result["overall"] == "DESCRIPTIVE_COMPARISON"
    assert result["comparability"] == "UNVERIFIED_CROSS_RUN_IDENTITY"


@pytest.mark.parametrize("patch", [
    lambda x: x["checks"]["SOCKET-EXCLUSIVITY"].update({"status": "OBSERVED"}),
    lambda x: x["checks"]["SOCKET-EXCLUSIVITY"].update({"reason": "exclusive_owner_verified"}),
    lambda x: x["checks"]["SOCKET-EXCLUSIVITY"].update({"extra": 1}),
    lambda x: x["checks"]["API-LISTENER"].update({"reason": "listener_identity_observed"}),
    lambda x: x["checks"].pop("SOCKET-EXCLUSIVITY"),
])
def test_nonexclusive_observation_cannot_forge_exclusive_owner(patch):
    invalid = nonexclusive_snapshot()
    patch(invalid)
    result = cli.compare(nonexclusive_snapshot(), invalid)
    assert result["overall"] == "INCOMPLETE"
    assert result["comparison"] is None


def test_legacy_observation_cannot_silently_import_nonexclusive_check():
    invalid = snapshot()
    invalid["checks"]["SOCKET-EXCLUSIVITY"] = {
        "status": "NOT_TESTED", "reason": "global_fd_scan_intentionally_not_run"}
    result = cli.compare(snapshot(), invalid)
    assert result["overall"] == "INCOMPLETE"
    assert result["comparison"] is None
