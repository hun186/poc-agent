#!/usr/bin/env python3
"""OFF-1V offline comparison of two *partial* OFF-1U API snapshots.

Reads only two bounded, existing, regular JSON files. It does NOT contact
any service, generate load, infer a shared host/PID, or claim live acceptance.
Input filenames and untrusted JSON content are never included in the output.

Usage:
  python tools/sraf_linux_load_compare_offline.py --idle-file idle.json --busy-file busy.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_linux_load_topology_readonly import SCHEMA as SNAPSHOT_SCHEMA  # noqa: E402

SCHEMA = "sraf_linux_load_compare_offline_v1"
MODE = "PARTIAL_ONLY_NOT_ACCEPTANCE"
MAX_JSON_BYTES = 32768
MAX_RSS_MIB = 10**10 / 1024

_EXPECTED_CHECKS = frozenset({
    "API-LISTENER", "API-MOUNT-NAMESPACE", "LOCAL-LOCK-CANDIDATE",
    "API-PROCESS-SAMPLES", "CROSS-WORKER-LOCK-SHARING", "OLLAMA-ES-TIMEOUT",
})
_NONEXCLUSIVE_CHECKS = _EXPECTED_CHECKS | {"SOCKET-EXCLUSIVITY"}
_EXPECTED_FIELDS = frozenset({
    "schema", "mode", "feature_acceptance", "overall", "checks", "samples",
    "network_requests", "credentials_sent", "database_queries",
    "model_inferences", "mutations", "processes_spawned",
})
_ALLOWED_CONTEXT = {
    "API-MOUNT-NAMESPACE": {
        ("OBSERVED", "same_namespace_as_operator_only"),
        ("SKIP", "different_mount_namespace"),
        ("SKIP", "mount_namespace_unverified"),
    },
    "LOCAL-LOCK-CANDIDATE": {
        ("OBSERVED", "local_lock_candidate_metadata_verified"),
        ("SKIP", "linux_only"),
        ("SKIP", "local_lock_candidate_untrusted"),
        ("SKIP", "local_lock_candidate_missing"),
        ("SKIP", "local_lock_candidate_unverified"),
    },
}


class ComparisonInputError(ValueError):
    """Fixed-category invalid input. Never embed paths, JSON or OS exceptions."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ComparisonInputError("snapshot_invalid")
        result[key] = value
    return result


def _read_existing_json(path: Path) -> object:
    """No symlinks/FIFO/device and no path disclosure; limit before reading."""
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                not 1 <= info.st_size <= MAX_JSON_BYTES):
            raise ComparisonInputError("snapshot_invalid")
        raw = os.read(fd, MAX_JSON_BYTES + 1)
        if len(raw) != info.st_size:
            raise ComparisonInputError("snapshot_invalid")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ComparisonInputError("snapshot_invalid")))
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ComparisonInputError("snapshot_invalid") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _validate_snapshot(value: object) -> list[dict[str, float | int]]:
    """Require actual OFF-1U partial observations, never accept forged PASS."""
    if not isinstance(value, dict) or set(value) != _EXPECTED_FIELDS:
        raise ComparisonInputError("snapshot_invalid")
    if (value["schema"] != SNAPSHOT_SCHEMA or
            value["mode"] != MODE or value["feature_acceptance"] != "NOT_TESTED" or
            value["overall"] != "PARTIAL_OBSERVATION"):
        raise ComparisonInputError("snapshot_invalid")
    for key in ("network_requests", "database_queries", "model_inferences",
                "mutations", "processes_spawned"):
        if type(value[key]) is not int or value[key] != 0:
            raise ComparisonInputError("snapshot_invalid")
    if value["credentials_sent"] is not False:
        raise ComparisonInputError("snapshot_invalid")
    checks = value["checks"]
    if not isinstance(checks, dict) or set(checks) not in (
            _EXPECTED_CHECKS, _NONEXCLUSIVE_CHECKS):
        raise ComparisonInputError("snapshot_invalid")
    new_observation = "SOCKET-EXCLUSIVITY" in checks
    expected_listener = (
        ("OBSERVED", "launcher_listener_for_local_sampling_only")
        if new_observation else ("OBSERVED", "listener_identity_observed")
    )
    expected = {
        "API-LISTENER": expected_listener,
        "API-PROCESS-SAMPLES": ("OBSERVED", "process_samples_collected"),
        "CROSS-WORKER-LOCK-SHARING": ("NOT_TESTED", "cannot_prove_from_external_snapshot"),
        "OLLAMA-ES-TIMEOUT": ("NOT_TESTED", "no_model_or_es_request"),
        "SOCKET-EXCLUSIVITY": (
            "NOT_TESTED", "global_fd_scan_intentionally_not_run"),
    }
    for key in _EXPECTED_CHECKS:
        row = checks[key]
        if not isinstance(row, dict) or set(row) != {"status", "reason"}:
            raise ComparisonInputError("snapshot_invalid")
        pair = (row["status"], row["reason"])
        if key in expected and pair != expected[key]:
            raise ComparisonInputError("snapshot_invalid")
        if key in _ALLOWED_CONTEXT and pair not in _ALLOWED_CONTEXT[key]:
            raise ComparisonInputError("snapshot_invalid")
    values = value["samples"]
    if not isinstance(values, list) or not 2 <= len(values) <= 5:
        raise ComparisonInputError("snapshot_invalid")
    samples: list[dict[str, float | int]] = []
    for index, row in enumerate(values, 1):
        if not isinstance(row, dict) or set(row) != {"sample", "rss_mib", "threads"}:
            raise ComparisonInputError("snapshot_invalid")
        rss = row["rss_mib"]
        threads = row["threads"]
        if (type(row["sample"]) is not int or row["sample"] != index or
                type(rss) not in (int, float) or
                not 0.1 <= rss <= MAX_RSS_MIB or
                not math.isfinite(rss) or round(rss, 1) != rss or
                type(threads) is not int or not 1 <= threads <= 131072):
            raise ComparisonInputError("snapshot_invalid")
        samples.append({"rss_mib": float(rss), "threads": threads})
    return samples


def compare(idle: object, busy: object) -> dict[str, object]:
    """Descriptive statistics only. No causal or cross-snapshot identity claim."""
    result = {
        "schema": SCHEMA, "mode": MODE, "feature_acceptance": "NOT_TESTED",
        "overall": "INCOMPLETE", "reason": "snapshot_invalid",
        "comparability": "UNVERIFIED_CROSS_RUN_IDENTITY",
        "cross_worker_lock_sharing": "NOT_TESTED",
        "ollama_es_timeout": "NOT_TESTED",
        "network_requests": 0, "model_inferences": 0, "database_queries": 0,
        "mutations": 0, "credentials_sent": False,
        "comparison": None,
    }
    try:
        left = _validate_snapshot(idle)
        right = _validate_snapshot(busy)
        # The OFF-1U schema doesn't include a trusted sample interval, host
        # identity, capture time or workload marker. Match sample count only.
        if len(left) != len(right):
            result["reason"] = "sample_count_mismatch"
            return result
    except (ComparisonInputError, TypeError):
        return result

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs)

    idle_rss = _mean([float(x["rss_mib"]) for x in left])
    busy_rss = _mean([float(x["rss_mib"]) for x in right])
    idle_threads = max(int(x["threads"]) for x in left)
    busy_threads = max(int(x["threads"]) for x in right)
    result["overall"] = "DESCRIPTIVE_COMPARISON"
    result["reason"] = "unverified_same_host_and_load_causality"
    result["comparison"] = {
        "sample_count_each": len(left),
        "idle_mean_rss_mib": round(idle_rss, 2),
        "busy_mean_rss_mib": round(busy_rss, 2),
        "mean_rss_delta_mib": round(busy_rss - idle_rss, 2),
        "mean_rss_delta_percent": round((busy_rss - idle_rss) / idle_rss * 100, 2),
        "idle_peak_threads": idle_threads,
        "busy_peak_threads": busy_threads,
        "peak_threads_delta": busy_threads - idle_threads,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-file", type=Path, required=True,
                        help="Local existing OFF-1U JSON (path never printed)")
    parser.add_argument("--busy-file", type=Path, required=True,
                        help="Local existing OFF-1U JSON (path never printed)")
    args = parser.parse_args(argv)
    try:
        result = compare(_read_existing_json(args.idle_file),
                         _read_existing_json(args.busy_file))
    except ComparisonInputError:
        result = compare(None, None)
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if result["overall"] == "DESCRIPTIVE_COMPARISON" else 2


if __name__ == "__main__":
    raise SystemExit(main())
