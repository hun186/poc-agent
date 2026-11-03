#!/usr/bin/env python3
"""OFF-2 optional active user-site dist-info fallback, read-only and partial only.

The original scheme-only runtime-deps command remains independent. Never
import declared packages, call pip, execute binaries, access services, install,
or treat user-specific packages as a reproducible production deployment.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import site
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_off2_runtime_deps as scheme

SCHEMA = "sraf_off2_direct_runtime_user_site_inventory_v1"
SCOPE = "SCHEME_PLUS_ACTIVE_USER_SITE_METADATA_ONLY_NOT_DEPLOYMENT_ATTESTATION"
SEARCH = "SELECTED_PYTHON_SCHEME_PLUS_ACTIVE_USER_SITE_DIST_INFO_ONLY"


def _result(status: str, reason: str, *, count: int = 0,
            scheme_count: int = 0, user_count: int = 0,
            unlocked: int = 0, exact_matches: int = 0,
            missing_positions: tuple[int, ...] = (),
            active: bool = False) -> dict[str, object]:
    found = scheme_count + user_count
    report = scheme._result(
        status, reason, count, found, unlocked, exact_matches, missing_positions,
    )
    report.update({
        "schema": SCHEMA, "scope": SCOPE,
        "metadata_search_scope": SEARCH,
        "scheme_installed_direct_count": scheme_count,
        "user_site_fallback_direct_count": user_count,
        "user_site_active": active,
        "user_site_release_attested": False,
    })
    return report


def _is_active_user_site(path: str, scheme_paths: tuple[str, ...]) -> bool:
    """One explicitly active configured path, not a broad sys.path traversal."""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        return False
    if path == "/" or path.endswith("/") or any(
            p in ("", ".", "..") for p in path.split("/")[1:]):
        return False
    if site.ENABLE_USER_SITE is not True or sys.flags.no_user_site:
        return False
    # The string check is an introspection hint, not a filesystem trust root:
    # open_directory_no_follow revalidates each component before reading.
    if path in scheme_paths:
        return False
    return path in sys.path


def observe(root: Path, *, scheme_paths: tuple[str, ...] | None = None,
            user_path: str | None = None) -> dict[str, object]:
    """Only inspect metadata in fixed scheme dirs + active user-site fallback.

    A non-active/non-readable site fails CLOSED; the function never turns
    installed user-site metadata into a full runtime/deployment acceptance.
    """
    try:
        wanted = scheme._declared(root)
    except (OSError, UnicodeError, scheme._UnsafeEvidence,
            scheme._InvalidInventory, ValueError, TypeError, RecursionError):
        return _result("INCOMPLETE", "requirements_input_unverifiable")
    count = len(wanted)
    unlocked = sum(value is None for value in wanted.values())
    try:
        if scheme_paths is None:
            scheme_paths = scheme._locations()
        direct = scheme._metadata_snapshot(set(wanted), scheme_paths)
    except (OSError, UnicodeError, scheme._UnsafeEvidence,
            scheme._InvalidInventory, ValueError, TypeError, RuntimeError, RecursionError):
        return _result("INCOMPLETE", "scheme_distribution_metadata_unverifiable",
                       count=count, unlocked=unlocked)

    base_count = len(direct)
    needed = set(wanted) - set(direct)
    if not needed:
        matched = sum(v is not None and direct.get(k) == v for k, v in wanted.items())
        if matched != count - unlocked:
            return _result("INCOMPLETE", "exact_direct_version_text_mismatch",
                           count=count, scheme_count=base_count,
                           unlocked=unlocked, exact_matches=matched)
        return _result("PASS_PARTIAL", "direct_metadata_in_scheme_only",
                       count=count, scheme_count=base_count,
                       unlocked=unlocked, exact_matches=matched)

    try:
        if user_path is None:
            user_path = site.getusersitepackages()
        if not _is_active_user_site(user_path, scheme_paths):
            return _result("INCOMPLETE", "active_user_site_unavailable",
                           count=count, scheme_count=base_count, unlocked=unlocked)
        # Existing bounded/no-follow checks (max 4096 directory entries, 1 MiB
        # selected METADATA each) are reused. Only names absent in the scheme
        # are read from the user-site; scheme metadata retains precedence.
        fallback = scheme._metadata_snapshot(needed, (user_path,))
        combined = dict(direct)
        combined.update(fallback)
        matched = sum(v is not None and combined.get(k) == v
                      for k, v in wanted.items())
        total = len(combined)
        if total < count:
            missing = tuple(i for i, name in enumerate(wanted, 1)
                            if name not in combined)
            return _result("INCOMPLETE", "direct_distribution_metadata_missing",
                           count=count, scheme_count=base_count,
                           user_count=len(fallback), unlocked=unlocked,
                           exact_matches=matched, missing_positions=missing,
                           active=True)
        if matched != count - unlocked:
            return _result("INCOMPLETE", "exact_direct_version_text_mismatch",
                           count=count, scheme_count=base_count,
                           user_count=len(fallback), unlocked=unlocked,
                           exact_matches=matched, active=True)
        return _result("PASS_PARTIAL",
                       "direct_metadata_observed_with_user_site_fallback_only",
                       count=count, scheme_count=base_count,
                       user_count=len(fallback), unlocked=unlocked,
                       exact_matches=matched, active=True)
    except (OSError, UnicodeError, scheme._UnsafeEvidence,
            scheme._InvalidInventory, ValueError, TypeError, RuntimeError, RecursionError):
        return _result("INCOMPLETE", "user_site_distribution_metadata_unverifiable",
                       count=count, scheme_count=base_count, unlocked=unlocked)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    output = observe(Path.cwd())
    print(json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0 if output["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
