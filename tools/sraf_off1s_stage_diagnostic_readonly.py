#!/usr/bin/env python3
"""Bounded operator-only OFF-1S stage diagnosis; NEVER a listener authority proof.

Same Unix account and PID namespace as the running SRAF API. Read-only
launcher/procfs inspection, no HTTP, token, process signal, restart or writes.
One attempt by default; optional bounded repetitions are observations, not
retries inside the live authenticated OFF-1S gate.

Only allowlisted stage labels and numeric counts are serialized. Traceback,
exception text, PID, inode, source identifiers, paths, and secrets are omitted.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_off1s_api_listener as listener  # noqa: E402

SCHEMA = "sraf_off1s_stage_diagnostic_readonly_v1"
# Ordered by the source's literal "return False" statements. If the source
# changes its branch structure, refuse to guess a reason (SOURCE_CHANGED).
SCAN_FALSE_REASONS = (
    "procfs_visibility_failed",
    "process_limit",
    "invalid_task_entry",
    "thread_limit",
    "fd_limit",
    "fd_disappeared",
    "fd_read_error",
    "another_socket_owner",
    "fd_table_scan_error",
    "empty_thread_table",
    "thread_table_race",
    "thread_table_scan_error",
    "global_proc_scan_error",
)
STAGES = (
    ("ROOT_PIN", "_pin_root_directory"),
    ("LAUNCHER_RECORD", "_identity"),
    ("PROCESS_IDENTITY", "_same_process"),
    ("LISTENER_INODE", "_listener_inode"),
    ("PID_SOCKET_OWNER", "_owns_socket"),
    ("PROCFS_VISIBILITY", "_procfs_unfiltered"),
    ("EXCLUSIVE_OWNER", "_exclusive_socket_owner"),
)
NUMERIC_FIELDS = ("process_count", "thread_count", "total_fds", "per_thread_fds")
MAX_EVENTS = 32


def _false_return_map(fn) -> dict[int, str]:
    try:
        source, start = inspect.getsourcelines(fn)
        lines = [start + i for i, line in enumerate(source)
                 if line.strip() == "return False"]
    except (OSError, TypeError):
        return {}
    if len(lines) != len(SCAN_FALSE_REASONS):
        return {line: "source_changed" for line in lines}
    return dict(zip(lines, SCAN_FALSE_REASONS))


def _safe_count(raw: Any) -> int | None:
    return raw if type(raw) is int and 0 <= raw <= 10_000_000 else None


def observe_once(*, root: Path = PROJECT_ROOT, port: str = "9002") -> dict[str, Any]:
    """Record one complete OFF-1S attestation, without patching core functions."""
    call_info: dict[int, tuple[str, float, str | None]] = {}
    stage_codes = {
        getattr(listener, name).__code__: stage for stage, name in STAGES
    }
    scan_code = listener._exclusive_socket_owner.__code__
    branch_names = _false_return_map(listener._exclusive_socket_owner)
    events: list[dict[str, Any]] = []
    start = time.monotonic()

    def trace(frame, event, arg):
        code = frame.f_code
        stage = stage_codes.get(code)
        if stage is None:
            return None
        ident = id(frame)
        if event == "call":
            call_info[ident] = (stage, time.monotonic(), None)
        elif event == "line" and code is scan_code and frame.f_lineno in branch_names:
            entry = call_info.get(ident)
            if entry is not None:
                call_info[ident] = (entry[0], entry[1], branch_names[frame.f_lineno])
        elif event == "return":
            entry = call_info.pop(ident, None)
            if entry is not None and len(events) < MAX_EVENTS:
                label, entered, branch = entry
                if label in ("ROOT_PIN", "LAUNCHER_RECORD", "LISTENER_INODE"):
                    success = arg is not None
                else:
                    success = arg is True
                safe = {
                    "stage": label,
                    "status": "PASS" if success else "INCOMPLETE",
                    "elapsed_ms": min(3_600_000, max(0, int(
                        (time.monotonic() - entered) * 1000))),
                }
                if label == "EXCLUSIVE_OWNER":
                    safe["reason"] = (
                        "verified" if success else
                        branch if branch is not None else "final_owner_or_procfs_unverified"
                    )
                    for item in NUMERIC_FIELDS:
                        safe[item] = _safe_count(frame.f_locals.get(item))
                events.append(safe)
        return trace

    previous_trace = sys.gettrace()
    try:
        sys.settrace(trace)
        try:
            proof = listener.attest_api_listener(root, port)
            status = "PASS" if proof is not None else "INCOMPLETE"
        except Exception:
            status = "INCOMPLETE"
    finally:
        sys.settrace(previous_trace)
    failed = next((row for row in events if row["status"] != "PASS"), None)
    return {
        "status": status,
        "failure_stage": (failed["stage"] if failed else
                          "NONE" if status == "PASS" else "UNOBSERVED"),
        "failure_reason": (failed.get("reason", "unverified") if failed else
                           "NONE" if status == "PASS" else "unverified"),
        "elapsed_ms": min(3_600_000, max(0, int((time.monotonic() - start) * 1000))),
        "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args(argv)
    rows = [observe_once() for _ in range(args.attempts)]
    result = {
        "schema": SCHEMA,
        "mode": "OPERATOR_READONLY_NO_HTTP_NO_AUTH_NO_RETRY_OF_LIVE_GATE",
        "scope": "OFF1S_LISTENER_IDENTITY_ONLY_NOT_E2E",
        "result": ("PASS_OBSERVED" if all(row["status"] == "PASS" for row in rows)
                   else "INCOMPLETE"),
        "attempts": rows,
        "credentials_sent": False,
        "http_requests": 0,
        "mutations": 0,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    # This diagnostic NEVER confers positive bearer authorization.
    return 0 if result["result"] == "PASS_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
