#!/usr/bin/env python3
"""Operator-run, offline-capable Report Job deployment acceptance.

Default: read-only local API/static and bounded network diagnostics; never login,
invoke a model, create a Job, import the API, or require Node.js.
--live-report: explicit authorized production Job (one POST, polling, DOCX).
No remote internet access, package installation, proxies, telemetry or retries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.sraf_airgap_off1_probes import _http_get
from tools.sraf_airgap_off1b_api_http import _observe as api_health_observe
from tools.sraf_airgap_off1b_auto import (
    _api_bind_endpoint, _effective_runtime_config, _observe as tcp_observe,
)
from tools.sraf_airgap_off1s_api_listener import (
    attest_api_listener, listener_still_expected,
)

SCHEMA = "sraf_airgap_report_jobs_acceptance_v1"
MODE = "PARTIAL_ONLY_NOT_AIRGAP_CERTIFICATION"
MAX_JSON = 32768
MAX_DOCX = 16 * 1024 * 1024
PROMPT = "請以繁體中文產生一份簡短的 SRAF 部署驗收測試報告，包含摘要、分析與結論。"
PHASES = frozenset(("queued", "unobserved", "agent_execution", "docx_export",
                    "finalizing", "completed", "failed", "interrupted"))
STATES = frozenset(("queued", "running", "completed", "failed", "interrupted"))
FAILURES = frozenset(("timeout", "rate_limited", "provider_unavailable", "execution_error"))
STATIC = (
    ("ui_page", "/report-jobs", b'report_jobs_ui.js'),
    ("ui_javascript", "/static/report_jobs_ui.js", b'/v1/report/jobs'),
    ("ui_stylesheet", "/static/report_jobs_ui.css", b''),
)


class ObservationError(Exception):
    """Only fixed, non-sensitive error codes can escape to evidence."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _row(name: str, status: str, reason: str, **values):
    return {"check": name, "status": status, "reason": reason, **values}


def _guard(proof, port: int):
    if proof is None or proof.port != port or not listener_still_expected(ROOT, proof):
        raise ObservationError("listener_identity_changed")


def _bounded_http(port: int, method: str, path: str, *, payload=None, token=None,
                  proof=None, max_body=MAX_JSON, timeout=12.0):
    """Strict numeric-loopback HTTP/1.1 with single absolute monotonic deadline.

    Check OFF-1S process/socket identity on an ALREADY CONNECTED socket before
    sending any credential (including login password) and again after reading.
    No urllib, DNS, redirects, proxy, netrc, chunked/decompression or retry.
    """
    if method not in ("POST", "GET") or not path.startswith("/") or re.fullmatch(
        r"/[A-Za-z0-9/_-]+", path
    ) is None:
        raise ObservationError("request_shape_invalid")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ObservationError("port_invalid")
    if proof is None:
        raise ObservationError("listener_unverified")
    body = b"" if payload is None else json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(body) > 8192:
        raise ObservationError("request_too_large")
    if token is not None and (
        not isinstance(token, str) or len(token) > 4096
        or not all(33 <= ord(ch) <= 126 for ch in token)
    ):
        raise ObservationError("credential_invalid")
    header = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Accept: application/json\r\n"
        "Accept-Encoding: identity\r\n"
        "Connection: close\r\n"
    )
    if method == "POST":
        header += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
    if token is not None:
        header += f"Authorization: Bearer {token}\r\n"
    packet = header.encode("ascii") + b"\r\n" + body
    deadline = time.monotonic() + timeout
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", port))
        _guard(proof, port)
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        sock.sendall(packet)
        frame = bytearray()
        while b"\r\n\r\n" not in frame:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ObservationError("http_deadline")
            sock.settimeout(left)
            part = sock.recv(min(4096, max_body + 4100 - len(frame)))
            if not part:
                raise ObservationError("http_incomplete")
            frame.extend(part)
            if len(frame) > max_body + 4100:
                raise ObservationError("http_oversized")
        raw_header, rest = bytes(frame).split(b"\r\n\r\n", 1)
        if len(raw_header) > 4096:
            raise ObservationError("http_header_oversized")
        lines = raw_header.split(b"\r\n")
        if re.fullmatch(rb"HTTP/1\.[01] [1-5][0-9]{2}(?: [\x20-\x7e]{0,100})?", lines[0]) is None:
            raise ObservationError("http_status_invalid")
        status = int(lines[0][9:12])
        headers = {}
        for line in lines[1:]:
            if b":" not in line:
                raise ObservationError("http_header_invalid")
            name, value = line.split(b":", 1)
            if re.fullmatch(rb"[A-Za-z0-9-]+", name) is None:
                raise ObservationError("http_header_invalid")
            key = name.lower()
            if key in headers or b"\x00" in value or b"\r" in value or b"\n" in value:
                raise ObservationError("http_header_invalid")
            headers[key] = value.strip()
        if b"transfer-encoding" in headers or b"content-encoding" in headers:
            raise ObservationError("http_encoding_unsupported")
        length = headers.get(b"content-length", b"")
        if re.fullmatch(rb"[0-9]{1,8}", length) is None or int(length) > max_body:
            raise ObservationError("http_length_invalid")
        expected = int(length)
        if len(rest) > expected:
            raise ObservationError("http_extra_bytes")
        chunks = [rest]
        count = len(rest)
        while count < expected:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ObservationError("http_deadline")
            sock.settimeout(left)
            part = sock.recv(min(65536, expected - count))
            if not part:
                raise ObservationError("http_incomplete")
            chunks.append(part)
            count += len(part)
        _guard(proof, port)
        if time.monotonic() >= deadline:
            raise ObservationError("http_deadline")
        return status, headers, b"".join(chunks)
    except (TimeoutError, socket.timeout):
        raise ObservationError("http_deadline") from None
    except OSError:
        raise ObservationError("http_transport_unavailable") from None
    finally:
        sock.close()


def _json_response(status, headers, raw, expected_status):
    if status != expected_status:
        raise ObservationError("http_status_" + str(status))
    if headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower() != b"application/json":
        raise ObservationError("http_media_invalid")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        raise ObservationError("http_json_invalid") from None
    if not isinstance(result, dict):
        raise ObservationError("http_json_invalid")
    return result


def _secure_output_dir(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ObservationError("output_dir_invalid")
    if (path.stat().st_mode & 0o077) != 0:
        raise ObservationError("output_permissions_unsafe")


def _secure_write(path: Path, raw: bytes):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _validate_docx(raw: bytes):
    if not 0 < len(raw) <= MAX_DOCX:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            if not 2 <= len(names) <= 1000 or len(names) != len(set(names)):
                return False
            if not {"[Content_Types].xml", "word/document.xml"} <= set(names):
                return False
            total = 0
            for info in z.infolist():
                parts = info.filename.split("/")
                if (info.filename.startswith("/") or "\\" in info.filename
                        or ".." in parts or "." in parts
                        or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK):
                    return False
                total += info.file_size
                if total > 64 * 1024 * 1024:
                    return False
            return z.getinfo("word/document.xml").file_size > 0 and z.testzip() is None
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        return False


def _quick(port: int, cfg: dict, rows: list, suite: str, no_network: bool):
    health = api_health_observe(cfg, no_network=no_network)
    hstat = health["http_probe"]
    rows.append(_row("api_health", hstat, str(health["reason"])))
    for name, path, marker in STATIC:
        if no_network:
            rows.append(_row(name, "SKIP", "network_disabled"))
            continue
        status, raw = _http_get(port, path)
        valid = status == 200 and raw is not None and (not marker or marker in raw)
        rows.append(_row(name, "PASS" if valid else "FAIL",
                         "asset_observed" if valid else "asset_unavailable"))
    if suite == "diagnose":
        for service in ("api", "es", "llm"):
            observed = tcp_observe(service, cfg, no_network=no_network)
            rows.append(_row("tcp_" + service, observed["tcp_probe"],
                             str(observed["reason"])))
    proof = None if no_network else attest_api_listener(ROOT, str(port))
    rows.append(_row("api_listener", "PASS" if proof else "SKIP",
                     "api_listener_attested" if proof else
                     "network_disabled" if no_network else "api_listener_unverified"))
    return proof


def _live(port: int, proof, args, rows: list, result_dir: Path):
    if proof is None:
        rows.append(_row("live_report", "SKIP", "listener_unverified_no_credentials_sent"))
        return 2
    token = None
    if args.token_env:
        token = os.environ.get(args.token_env, "")
        if not token:
            rows.append(_row("authentication", "SKIP", "token_env_missing"))
            return 2
        rows.append(_row("authentication", "PASS", "operator_token_supplied"))
    else:
        if not sys.stdin.isatty():
            rows.append(_row("authentication", "SKIP", "interactive_login_required"))
            return 2
        username = args.username or input("SRAF username: ").strip()
        password = getpass.getpass("SRAF password: ")
        if not username or not password:
            rows.append(_row("authentication", "FAIL", "login_input_empty"))
            return 1
        try:
            response = _bounded_http(port, "POST", "/v1/auth/login",
                                     payload={"username": username, "password": password},
                                     proof=proof)
            login = _json_response(*response, expected_status=200)
            token = login.get("access_token")
            if not isinstance(token, str) or not token:
                raise ObservationError("login_token_invalid")
            rows.append(_row("authentication", "PASS", "login_authenticated"))
        finally:
            password = None
    payload = {"prompt": PROMPT, "filename": "SRAF_部署驗收.docx"}
    job = _json_response(*_bounded_http(
        port, "POST", "/v1/report/jobs", payload=payload, token=token, proof=proof
    ), expected_status=202)
    job_id = job.get("job_id")
    if not isinstance(job_id, str) or re.fullmatch(r"rpt_[0-9a-f]{32}", job_id) is None:
        raise ObservationError("job_create_shape_invalid")
    rows.append(_row("report_create", "PASS", "job_created"))
    start = time.monotonic()
    phases = []
    state = "running"
    while time.monotonic() - start < args.max_seconds:
        response = _bounded_http(port, "GET", "/v1/report/jobs/" + job_id,
                                 token=token, proof=proof)
        info = _json_response(*response, expected_status=200)
        if info.get("job_id") != job_id:
            raise ObservationError("job_owner_identity_mismatch")
        state = info.get("status")
        progress = info.get("progress")
        if state not in STATES or not isinstance(progress, dict):
            raise ObservationError("job_progress_invalid")
        phase = progress.get("phase")
        if phase not in PHASES:
            raise ObservationError("job_phase_unknown")
        if not phases or phases[-1] != phase:
            phases.append(phase)
            if len(phases) > 32:
                raise ObservationError("job_phase_sequence_unbounded")
        if state in ("completed", "failed", "interrupted"):
            break
        time.sleep(3)
    else:
        rows.append(_row("report_progress", "SKIP", "observation_budget_exceeded",
                         phases=phases, duration_seconds=round(time.monotonic() - start)))
        return 2
    rows.append(_row("report_progress", "PASS" if state == "completed" else "FAIL",
                     "job_completed" if state == "completed" else "job_terminal_failure",
                     phases=phases, duration_seconds=round(time.monotonic() - start),
                     failure_category=(
                         progress.get("failure_category")
                         if progress.get("failure_category") in FAILURES else None
                     )))
    if state != "completed":
        return 1
    http_status, headers, word = _bounded_http(
        port, "GET", "/v1/report/jobs/" + job_id + "/word", token=token,
        proof=proof, max_body=MAX_DOCX, timeout=60.0
    )
    valid = (http_status == 200 and
             headers.get(b"content-type", b"").split(b";", 1)[0].lower() ==
             b"application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             and _validate_docx(word))
    if not valid:
        rows.append(_row("report_docx", "FAIL", "docx_invalid"))
        return 1
    filename = ("report-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-" + os.urandom(5).hex() + ".docx")
    _secure_write(result_dir / filename, word)
    rows.append(_row("report_docx", "PASS", "docx_integrity_checked",
                     size_bytes=len(word), sha256=hashlib.sha256(word).hexdigest()))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("quick", "diagnose"), default="quick")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--live-report", action="store_true",
                        help="EXPLICIT permission: create one real LLM/Agent job")
    parser.add_argument("--username", default=None, help="SRAF username; password prompted")
    parser.add_argument("--token-env", default=None,
                        help="Name of environment variable holding existing scoped token")
    parser.add_argument("--max-seconds", type=int, default=1200)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "sraf-acceptance-results")
    args = parser.parse_args(argv)
    if args.live_report and args.no_network:
        parser.error("--live-report is incompatible with --no-network")
    if args.token_env and re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", args.token_env) is None:
        parser.error("invalid --token-env NAME")
    if not 30 <= args.max_seconds <= 3600:
        parser.error("--max-seconds must be between 30 and 3600")
    if Path.cwd().resolve() != ROOT:
        print("SRAF_ACCEPTANCE=INCOMPLETE reason=run_from_repository_root")
        return 2
    rows = []
    report = {"schema": SCHEMA, "mode": MODE, "suite": args.suite,
              "live_report_requested": args.live_report, "checks": rows,
              "full_airgap_acceptance": "NOT_TESTED",
              "browser_visual_acceptance": "NOT_TESTED",
              "es_sql_provider_provenance": "NOT_TESTED"}
    code = 2
    try:
        _secure_output_dir(args.output_dir)
        cfg = _effective_runtime_config(ROOT)
        endpoint, host = _api_bind_endpoint(cfg)
        if endpoint["configuration"] != "RESOLVED" or host != "127.0.0.1":
            raise ObservationError("api_port_invalid")
        port = int(endpoint["port"])
        proof = _quick(port, cfg, rows, args.suite, args.no_network)
        required = [r for r in rows if r["check"] in
                    ("api_health", "ui_page", "ui_javascript", "ui_stylesheet")]
        code = (1 if any(r["status"] == "FAIL" for r in required) else
                2 if any(r["status"] != "PASS" for r in required) else 0)
        if args.live_report and code == 0:
            code = _live(port, proof, args, rows, args.output_dir)
        elif args.live_report:
            rows.append(_row("live_report", "SKIP", "quick_checks_not_passed"))
    except ObservationError as exc:
        rows.append(_row("operator", "SKIP" if "unverified" in exc.code else "FAIL", exc.code))
        code = 2 if "unverified" in exc.code else 1
    except (OSError, ValueError, RuntimeError, EOFError, KeyboardInterrupt):
        rows.append(_row("operator", "SKIP", "operator_environment_or_transport_unavailable"))
        code = 2
    report["result"] = "PASS_PARTIAL" if code == 0 else "FAIL" if code == 1 else "INCOMPLETE"
    report["exit_code"] = code
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        name = "report-jobs-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(3).hex() + ".json"
        _secure_write(args.output_dir / name, json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8"))
        print("SRAF_REPORT_JOBS_ACCEPTANCE=" + report["result"])
        for r in rows:
            print(r["check"] + "=" + r["status"] + " reason=" + r["reason"])
        print("EVIDENCE_FILE=" + str(args.output_dir / name))
    except OSError:
        print("SRAF_REPORT_JOBS_ACCEPTANCE=INCOMPLETE reason=evidence_write_unavailable")
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
