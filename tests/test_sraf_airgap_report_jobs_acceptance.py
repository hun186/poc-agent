"""Offline operator acceptance checks; no network/LLM/production services in CI."""
import io
import json
import os
from pathlib import Path
import zipfile

import pytest

from tools import sraf_airgap_report_jobs_acceptance as a


def _docx():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("[Content_Types].xml", "<Types/>")
        out.writestr("word/document.xml", "<document><body>OK</body></document>")
    return buffer.getvalue()


def test_valid_docx_and_negative_zip():
    assert a._validate_docx(_docx())
    assert not a._validate_docx(b"not-a-zip")
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape", "x")
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<document/>")
    assert not a._validate_docx(bad.getvalue())


def test_public_quick_probe_no_credentials_no_models(monkeypatch):
    called = []
    monkeypatch.setattr(a, "api_health_observe", lambda c, no_network: {
        "http_probe": "PASS", "reason": "healthz_http_200"})
    def fake_get(port, path):
        called.append(path)
        return 200, b"report_jobs_ui.js /v1/report/jobs"
    monkeypatch.setattr(a, "_http_get", fake_get)
    monkeypatch.setattr(a, "attest_api_listener", lambda root, port: None)
    rows = []
    proof = a._quick(9002, {}, rows, "quick", no_network=False)
    assert proof is None
    assert called == ["/report-jobs", "/static/report_jobs_ui.js",
                      "/static/report_jobs_ui.css"]
    assert [x["status"] for x in rows] == ["PASS"] * 4 + ["SKIP"]
    assert all("token" not in json.dumps(row).lower() for row in rows)


def test_quick_no_network_sends_nothing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no network or listener attestation in config-only mode")
    monkeypatch.setattr(a, "_http_get", forbidden)
    monkeypatch.setattr(a, "attest_api_listener", forbidden)
    monkeypatch.setattr(a, "tcp_observe", lambda name, cfg, no_network: {
        "tcp_probe": "SKIP", "reason": "network_disabled"})
    monkeypatch.setattr(a, "api_health_observe", lambda cfg, no_network: {
        "http_probe": "SKIP", "reason": "network_disabled"})
    rows = []
    assert a._quick(9002, {}, rows, "diagnose", no_network=True) is None
    assert len(rows) == 8
    assert all(r["status"] == "SKIP" for r in rows)


def test_live_requires_verified_listener_before_any_login_or_network(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "_bounded_http", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("no authenticated request allowed")))
    rows = []
    args = type("Args", (), {"token_env": None})()
    assert a._live(9002, None, args, rows, tmp_path) == 2
    assert rows == [a._row("live_report", "SKIP", "listener_unverified_no_credentials_sent")]


def test_real_job_uses_one_post_polls_and_checks_docx_without_secrets(monkeypatch, tmp_path):
    calls = []
    token = "private-TEST-TOKEN"
    monkeypatch.setenv("SRAF_ACCEPTANCE_TOKEN_TEST", token)
    job_id = "rpt_" + "a" * 32
    docx = _docx()
    def fake_http(port, method, path, **kwargs):
        calls.append((method, path, kwargs.get("token")))
        if path == "/v1/report/jobs":
            assert kwargs["payload"]["filename"] == "SRAF_部署驗收.docx"
            return 202, {b"content-type": b"application/json"}, json.dumps({
                "job_id": job_id, "status": "queued"}).encode()
        if path.endswith("/word"):
            return 200, {b"content-type":
                b"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}, docx
        if path.endswith(job_id) and len([c for c in calls if c[1] == path]) == 1:
            data = {"job_id": job_id, "status": "running",
                    "progress": {"phase": "agent_execution"}}
        else:
            data = {"job_id": job_id, "status": "completed",
                    "progress": {"phase": "completed"}}
        return 200, {b"content-type": b"application/json"}, json.dumps(data).encode()
    monkeypatch.setattr(a, "_bounded_http", fake_http)
    monkeypatch.setattr(a.time, "sleep", lambda n: None)
    args = type("Args", (), {"token_env": "SRAF_ACCEPTANCE_TOKEN_TEST", "max_seconds": 60})()
    rows = []
    assert a._live(9002, object(), args, rows, tmp_path) == 0
    assert [r["check"] for r in rows] == [
        "authentication", "report_create", "report_progress", "report_docx"]
    assert rows[-1]["sha256"]
    saved = list(tmp_path.glob("report-*.docx"))
    assert len(saved) == 1 and saved[0].read_bytes() == docx
    assert saved[0].stat().st_mode & 0o777 == 0o600
    assert [x[:2] for x in calls] == [
        ("POST", "/v1/report/jobs"),
        ("GET", "/v1/report/jobs/" + job_id),
        ("GET", "/v1/report/jobs/" + job_id),
        ("GET", "/v1/report/jobs/" + job_id + "/word")]
    assert all(t == token for _, _, t in calls)
    report_text = json.dumps(rows, ensure_ascii=False)
    assert token not in report_text and job_id not in report_text


def test_no_duplicate_submission_when_first_post_fails(monkeypatch, tmp_path):
    count = 0
    monkeypatch.setenv("SRAF_ACCEPTANCE_TOKEN_TEST", "secret")
    def fail(*args, **kwargs):
        nonlocal count
        count += 1
        raise a.ObservationError("http_deadline")
    monkeypatch.setattr(a, "_bounded_http", fail)
    args = type("Args", (), {"token_env": "SRAF_ACCEPTANCE_TOKEN_TEST", "max_seconds": 60})()
    with pytest.raises(a.ObservationError, match="http_deadline"):
        a._live(9002, object(), args, [], tmp_path)
    assert count == 1


def test_evidence_mode_0600_and_refuses_existing_file(tmp_path):
    folder = tmp_path / "output"
    a._secure_output_dir(folder)
    assert folder.stat().st_mode & 0o777 == 0o700
    file = folder / "evidence.json"
    a._secure_write(file, b'{"result":"PASS_PARTIAL"}')
    assert file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        a._secure_write(file, b"overwrite")
    assert file.read_bytes() == b'{"result":"PASS_PARTIAL"}'


def test_listener_guard_fail_closed(monkeypatch):
    monkeypatch.setattr(a, "listener_still_expected", lambda root, proof: False)
    proof = type("Proof", (), {"port": 9002})()
    with pytest.raises(a.ObservationError, match="listener_identity_changed"):
        a._guard(proof, 9002)


def test_default_cli_no_llm_and_redacted_output(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(a, "ROOT", tmp_path)
    monkeypatch.setattr(a, "_effective_runtime_config", lambda root: {})
    monkeypatch.setattr(a, "_api_bind_endpoint", lambda cfg: (
        {"configuration": "RESOLVED", "port": 9002}, "127.0.0.1"))
    def fake_quick(port, cfg, rows, suite, no_network):
        rows.extend([a._row(x, "PASS", "asset_observed") for x in
                     ("api_health", "ui_page", "ui_javascript", "ui_stylesheet")])
        return None
    monkeypatch.setattr(a, "_quick", fake_quick)
    assert a.main([]) == 0
    output = capsys.readouterr().out
    assert "SRAF_REPORT_JOBS_ACCEPTANCE=PASS_PARTIAL" in output
    files = list((tmp_path / "sraf-acceptance-results").glob("*.json"))
    assert len(files) == 1
    report = json.loads(files[0].read_text())
    assert report["live_report_requested"] is False
    assert report["full_airgap_acceptance"] == "NOT_TESTED"
