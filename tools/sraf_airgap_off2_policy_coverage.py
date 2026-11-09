#!/usr/bin/env python3
"""OFF-2 advisory audit: minimum operator entrypoint selection in release policy.

No package, signature, wheelhouse, provenance or disconnected deployment proof.
Never reads secret data, queries a service, changes policy or modifies any file.
All reported fields are fixed labels and counts, not local paths or raw errors.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.deployment_manifest import ManifestError, _validate_policy
from tools.sraf_airgap_off2_manifest_check import (
    _UnsafeEvidence, _fingerprint, _flags, _open_beneath,
)

POLICY = "tools/deployment_manifest_policy.json"
MAX_POLICY_BYTES = 1024 * 1024
SCOPE = "POLICY_SELECTION_ONLY_NOT_RELEASE_OR_AIRGAP_ATTESTATION"

# Deliberate *minimum*, not a complete release manifest or recursive discovery.
# The selection must be exact: broad "tools/" inclusion is not sufficient to
# audit independently reviewed release-tool paths.
REQUIRED_OPERATOR_FILES = (
    "scripts/diagnostics/run_sraf_airgap_offline.sh",
    "scripts/diagnostics/run_sraf_airgap_off1_diagnose.sh",
    "scripts/diagnostics/run_sraf_airgap_off2_verify.sh",
    "tools/sraf_airgap_off1_hub.py",
    "tools/sraf_airgap_off1_es_hub.py",
    "tools/sraf_airgap_off1_sql_hub.py",
    "tools/sraf_airgap_off1_text_report.py",
    "tools/sraf_airgap_off2_manifest_check.py",
    "tools/sraf_airgap_off2_policy_coverage.py",
    "1_完整診斷驗收_SRAF.sh",
    "tools/sraf_operator_diagnostics.py",
    "tools/sraf_diagnostics_report.py",
    "tools/sraf_private_report_store.py",
)


def _selected_by_policy(path: str, policy: dict[str, object]) -> bool:
    # Entry scripts are managed root files; independent CLI modules are
    # release tools. A broad directory selector is not an explicit review.
    key = "release_tool_files" if path.startswith("tools/") else "managed_files"
    return path in policy[key]


def observe(root: Path) -> dict[str, object]:
    """Advisory only; even a complete minimum selection is not verified bytes."""
    fd = -1
    checked = 0
    try:
        fd = os.open(root, _flags(directory=True))
        _, _, raw = _fingerprint(fd, POLICY, MAX_POLICY_BYTES, contents=True)
        assert raw is not None
        policy = _validate_policy(json.loads(raw.decode("utf-8")))
        for path in REQUIRED_OPERATOR_FILES:
            candidate = _open_beneath(fd, path)
            try:
                if not stat.S_ISREG(os.fstat(candidate).st_mode):
                    raise _UnsafeEvidence
            finally:
                os.close(candidate)
            checked += 1
        missing = sum(not _selected_by_policy(path, policy)
                      for path in REQUIRED_OPERATOR_FILES)
        if missing:
            return {"status": "INCOMPLETE", "reason": "required_operator_tools_unlisted",
                    "files_checked": checked, "unlisted_count": missing}
        return {"status": "PASS_PARTIAL",
                "reason": "minimum_policy_selection_only",
                "files_checked": checked, "unlisted_count": 0}
    except (OSError, _UnsafeEvidence, ManifestError, ValueError,
            TypeError, UnicodeError, RecursionError, AssertionError):
        return {"status": "INCOMPLETE", "reason": "policy_or_tool_unverifiable",
                "files_checked": checked, "unlisted_count": 0}
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> int:
    result = observe(Path.cwd())
    print("SRAF_OFF2_POLICY=" + str(result["status"])
          + " reason=" + str(result["reason"])
          + " files_checked=" + str(result["files_checked"])
          + " unlisted_count=" + str(result["unlisted_count"])
          + " scope=" + SCOPE)
    return 0 if result["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
