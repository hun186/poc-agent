#!/usr/bin/env python3
"""OFF-1W: passive /proc-only Ollama candidate-process resource sampler.

This is NOT Ollama authentication, model latency, GPU utilization or acceptance.
The process comm field is spoofable and may be truncated to 15 characters.
No HTTP, inference, subprocess, environ/cmdline, credentials, FD scan or writes.

Usage: python tools/sraf_ollama_proc_passive.py --samples 3 --interval 5
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off1s_api_listener import _bounded, _start_tick  # noqa: E402
from tools.sraf_linux_load_topology_readonly import _sample  # noqa: E402

SCHEMA = "sraf_ollama_proc_passive_v1"
MODE = "PARTIAL_ONLY_NOT_ACCEPTANCE"
MAX_PROCESSES = 20000
MAX_CANDIDATES = 16
# Linux /proc/<pid>/comm truncates TASK_COMM_LEN to 15 visible bytes.
_CANDIDATE_COMMS = frozenset({b"ollama", b"ollama_llama_se"})


def _row(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def _comm(pid: int) -> bytes | None:
    try:
        data = _bounded(Path(f"/proc/{pid}/comm"), 64)
    except (OSError, ValueError):
        return None
    if data is None:
        return None
    data = data.removesuffix(b"\n")
    return data if data in _CANDIDATE_COMMS else None


def _discover() -> dict[int, str] | None:
    """Bounded, current PID-namespace only; do not traverse task/FD tables."""
    found: dict[int, str] = {}
    count = 0
    try:
        with os.scandir("/proc") as entries:
            for item in entries:
                if not item.name.isascii() or not item.name.isdecimal():
                    continue
                count += 1
                if count > MAX_PROCESSES:
                    return None
                pid = int(item.name)
                if _comm(pid) is None:
                    continue
                tick = _start_tick(pid)
                if (tick is None or _comm(pid) is None or
                        _start_tick(pid) != tick):
                    return None  # process discovery churn; no inferred identity
                found[pid] = tick
                if len(found) > MAX_CANDIDATES:
                    return None
    except (OSError, ValueError):
        return None
    return found


def observe(*, samples: int = 3, interval: float = 5.0) -> dict[str, object]:
    checks = {
        "OLLAMA-CANDIDATES": _row("SKIP", "candidates_unverified"),
        "OLLAMA-PROCESS-SAMPLES": _row("SKIP", "sample_unverified"),
        "OLLAMA-PROCESS-COVERAGE": _row("NOT_TESTED", "current_pid_namespace_only"),
        "OLLAMA-IDENTITY": _row("NOT_TESTED", "process_comm_match_not_authentication"),
        "OLLAMA-GPU": _row("NOT_TESTED", "no_gpu_query"),
        "OLLAMA-LATENCY": _row("NOT_TESTED", "no_model_request"),
        "SRAF-E2E": _row("NOT_TESTED", "no_report_job"),
    }
    result: dict[str, object] = {
        "schema": SCHEMA, "mode": MODE, "feature_acceptance": "NOT_TESTED",
        "overall": "INCOMPLETE", "checks": checks, "samples": [],
        "network_requests": 0, "credentials_sent": False,
        "database_queries": 0, "model_inferences": 0,
        "mutations": 0, "processes_spawned": 0,
    }
    if (sys.platform != "linux" or type(samples) is not int or
            not 2 <= samples <= 5 or type(interval) not in (int, float) or
            not math.isfinite(interval) or not 0 <= interval <= 20):
        return result
    try:
        hz = os.sysconf("SC_CLK_TCK")
        if type(hz) is not int or hz <= 0:
            return result
        baseline = _discover()
        if baseline is None:
            checks["OLLAMA-CANDIDATES"] = _row("SKIP", "candidate_discovery_unverified")
            return result
        if not baseline:
            checks["OLLAMA-CANDIDATES"] = _row("SKIP", "no_visible_candidate")
            return result
        checks["OLLAMA-CANDIDATES"] = _row("OBSERVED", "process_comm_candidates_only")
        measurements = []
        first_ticks = None
        for i in range(samples):
            if _discover() != baseline:
                checks["OLLAMA-PROCESS-SAMPLES"] = _row("SKIP", "candidate_set_changed")
                return result
            readings = []
            for pid, start_tick in sorted(baseline.items()):
                if _comm(pid) is None:
                    checks["OLLAMA-PROCESS-SAMPLES"] = _row("SKIP", "candidate_set_changed")
                    return result
                reading = _sample(pid, start_tick)
                if reading is None or _comm(pid) is None:
                    checks["OLLAMA-PROCESS-SAMPLES"] = _row("SKIP", "candidate_sample_unverified")
                    return result
                readings.append(reading)
            ticks = sum(int(x["cpu_ticks"]) for x in readings)
            if first_ticks is None:
                first_ticks = ticks
            if ticks < first_ticks:
                checks["OLLAMA-PROCESS-SAMPLES"] = _row("SKIP", "cpu_counter_unverified")
                return result
            measurements.append({
                "sample": i + 1,
                "candidate_count": len(baseline),
                "rss_sum_mib": round(sum(int(x["rss_kib"]) for x in readings) / 1024, 1),
                "threads_sum": sum(int(x["threads"]) for x in readings),
                "cpu_seconds_since_first": round((ticks - first_ticks) / hz, 3),
            })
            if i + 1 < samples:
                time.sleep(interval)
        if _discover() != baseline:
            checks["OLLAMA-PROCESS-SAMPLES"] = _row("SKIP", "candidate_set_changed")
            return result
        checks["OLLAMA-PROCESS-SAMPLES"] = _row("OBSERVED", "numeric_proc_samples_collected")
        result["overall"] = "PARTIAL_OBSERVATION"
        result["samples"] = measurements
    except (OSError, ValueError, OverflowError, TypeError):
        checks["OLLAMA-PROCESS-SAMPLES"] = _row("SKIP", "candidate_sample_unverified")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, choices=range(2, 6), default=3)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args(argv)
    result = observe(samples=args.samples, interval=args.interval)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False))
    return 0 if result["overall"] == "PARTIAL_OBSERVATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
