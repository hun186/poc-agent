#!/usr/bin/env python3
"""OFF-2 read-only direct-requirements pin diagnostic (NOT wheelhouse attestation).

Checks only the first-party requirements.txt.  It does not resolve transitive
dependencies, inspect installed distributions or wheels, download, install,
sign or execute untrusted package content.  Output is fixed labels and counts.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_manifest_check import _UnsafeEvidence, _fingerprint, _flags

REQUIREMENTS = "requirements.txt"
MAX_REQUIREMENTS_BYTES = 64 * 1024
MAX_REQUIREMENTS_LINES = 1024
SCOPE = "DIRECT_PINS_ONLY_NOT_WHEELHOUSE_OR_AIRGAP_ATTESTATION"

# Intentionally limited to a small, auditable literal subset.  Include files,
# remote/VCS references, index options, extras/markers requiring interpretation,
# editable installs and continuations must never be silently treated as pinned.
_LITERAL_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<operator>===|==|~=|!=|>=|<=|>|<)"
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9.!+*_-]*)"
)
_EXACT_VERSION = re.compile(r"[0-9][A-Za-z0-9.!+_-]*")


def _result(status: str, reason: str, checked: int = 0,
            unpinned: int = 0) -> dict[str, object]:
    return {"status": status, "reason": reason,
            "requirements_checked": checked, "unpinned_count": unpinned}


def observe(root: Path) -> dict[str, object]:
    """Read a bounded no-follow source; never claim dependency closure."""
    fd = -1
    try:
        fd = os.open(root, _flags(directory=True))
        _, _, raw = _fingerprint(fd, REQUIREMENTS, MAX_REQUIREMENTS_BYTES,
                                 contents=True)
        assert raw is not None
        value = raw.decode("utf-8")
        if "\x00" in value or "\ufeff" in value or "\r" in value.replace("\r\n", ""):
            return _result("INCOMPLETE", "requirement_syntax_unsupported")
        lines = value.splitlines()
        if len(lines) > MAX_REQUIREMENTS_LINES:
            return _result("INCOMPLETE", "requirement_input_unverifiable")
        checked = 0
        unlocked = 0
        for line in lines:
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            match = _LITERAL_REQUIREMENT.fullmatch(item)
            if match is None:
                return _result("INCOMPLETE", "requirement_syntax_unsupported",
                               checked, unlocked)
            checked += 1
            if match["operator"] != "==" or not _EXACT_VERSION.fullmatch(match["version"]):
                unlocked += 1
        if checked == 0:
            return _result("INCOMPLETE", "requirements_empty")
        if unlocked:
            return _result("INCOMPLETE", "direct_versions_unpinned", checked, unlocked)
        return _result("PASS_PARTIAL", "direct_versions_pinned_only", checked)
    except (OSError, _UnsafeEvidence, ValueError, UnicodeError, RecursionError,
            AssertionError):
        return _result("INCOMPLETE", "requirement_input_unverifiable")
    finally:
        if fd >= 0:
            os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = observe(Path.cwd())
    print("SRAF_OFF2_DEPS=" + str(result["status"])
          + " reason=" + str(result["reason"])
          + " requirements_checked=" + str(result["requirements_checked"])
          + " unpinned_count=" + str(result["unpinned_count"])
          + " scope=" + SCOPE)
    return 0 if result["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
