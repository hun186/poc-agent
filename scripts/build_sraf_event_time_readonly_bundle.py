#!/usr/bin/env python3
"""Build a small no-Git-on-Linux, stdlib ZIP sidecar for SRAF #393.

Run on the Windows development checkout AFTER git fetch has updated the
desired PR #395 source version, or on hosted CI as a fallback. The archive carries
an explicit allowlist of Python source and a one-command runner. It does not
copy .env, private TLS certificates, reports, databases, secrets, or .git.
Linux receives a ZIP over the EXISTING one-way incremental Robocopy/7z route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = "_sraf_date_readonly"
FILES = (
    "tools/__init__.py",
    "tools/sraf_event_time_readonly_acceptance.py",
    "tools/sraf_airgap_off1b_auto.py",
    "tools/sraf_airgap_off1b_es_https_mapping.py",
    "tools/sraf_airgap_off1_probes.py",
    "config/bootstrap.py",
    "agent/__init__.py",
    "agent/e2e_preflight_budget.py",
    "agent/external_capabilities.py",
    "agent/es/__init__.py",
    "agent/es/reference_text.py",
    "agent/es/event_time.py",
    "agent/es/query_body.py",
    "docs/operations/sraf_event_time_live_readonly.md",
)
RUNNER = """#!/usr/bin/env bash
# Isolated GET-only news_test verification; no Git, deploy, restart, or writes.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$ROOT"
PYTHON_BIN="${SRAF_PYTHON:-python}"
# Support both existing overlay (poc-agent/_sraf_date_readonly) and an
# isolated sibling (TopicClassification/_sraf_date_readonly), with override.
PARENT="$(cd -- "$ROOT/.." && pwd -P)"
if [[ -n "${SRAF_CONFIG_ROOT:-}" ]]; then
  DEPLOY_ROOT="$SRAF_CONFIG_ROOT"
elif [[ -f "$PARENT/run_sra_api.sh" ]]; then
  DEPLOY_ROOT="$PARENT"
else
  DEPLOY_ROOT="$PARENT/poc-agent"
fi
exec "$PYTHON_BIN" tools/sraf_event_time_readonly_acceptance.py \
  --run --config-root "$DEPLOY_ROOT" "$@"
"""
README = """SRAF #393 / PR #395 | NEWS_TEST STRICT READ-ONLY SIDECAR

This folder is a self-contained source-only diagnostic subset; it is NOT a
runtime update, deployment script, migration, or official release approval.

Primary workflow: Windows local git fetch / select PR #395 source,
run 'python scripts/build_sraf_event_time_readonly_bundle.py' locally, and
upload dist/sraf-date-readonly.zip using your existing ONE-WAY incremental
transfer path. GitHub Actions artifact is an optional fallback, not required.
Prefer extraction next to the live poc-agent folder (no active runtime files
overwritten):

    cd /mntCZJ/TopicClassification
    7z x /path/to/sraf-date-readonly.zip -y
    bash _sraf_date_readonly/run.sh

No git pull/fetch/worktree on Linux. An existing 7z overlay can instead
place _sraf_date_readonly *inside* poc-agent; the runner auto-detects either
layout. No active runtime source is overwritten or restarted.
By default the runner reads ONLY the existing poc-agent .env.local and CA.
To choose another deployed directory, set SRAF_CONFIG_ROOT before execution.

Strict TLS CA + IP SAN is required. Existing SAN WARN becomes INCOMPLETE;
never disable certificate verification. The sole output is redacted JSON.
PASS_PARTIAL and INCOMPLETE exit 2; only a confirmed FAIL exits 1.
Even PASS_PARTIAL is NOT real FULL_LIVE validation or authorization to merge.
"""


def _zip_entry(archive: ZipFile, name: str, content: bytes, *, executable=False):
    entry = ZipInfo(f"{BUNDLE_DIR}/{name}", date_time=(2020, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.create_system = 3
    entry.external_attr = (0o100755 if executable else 0o100644) << 16
    archive.writestr(entry, content, compresslevel=9)


def _source_head(root: Path) -> str:
    # HEAD is relevant only to the packaging machine, never to Linux.
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode("ascii", errors="strict").strip()
        return output if re.fullmatch(r"[0-9a-f]{40}", output) else "NOT_VERIFIED"
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            UnicodeError):
        return "NOT_VERIFIED"


def build(root: Path, output: Path, *, source_head: str | None = None) -> dict:
    files: dict[str, bytes] = {}
    for path in FILES:
        if path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("unsafe_file_allowlist")
        file = root / path
        if not file.is_file() or file.is_symlink():
            raise FileNotFoundError(f"missing_or_symlink_source:{path}")
        files[path] = file.read_bytes()
    files["run.sh"] = RUNNER.encode("utf-8")
    files["README.txt"] = README.encode("utf-8")
    head = source_head or _source_head(root)
    manifest = {
        "schema": "sraf_event_time_readonly_sidecar_v1",
        "scope": "fixed_news_test_get_only",
        "source_head": head,
        "file_count": len(files),
        "files_sha256": {
            k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())
        },
        "no_git_required_on_linux": True,
        "active_runtime_overwrite": False,
        "full_live_acceptance": False,
    }
    files["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        for name, payload in sorted(files.items()):
            _zip_entry(archive, name, payload, executable=name == "run.sh")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "dist" / "sraf-date-readonly.zip",
    )
    parser.add_argument(
        "--source-head", default=None,
        help="Optional 40-char reviewed SHA, from build CI. No Git on Linux.",
    )
    args = parser.parse_args(argv)
    if args.source_head and not re.fullmatch(r"[0-9a-f]{40}", args.source_head):
        parser.error("source-head must be exactly a 40-digit lowercase SHA")
    manifest = build(ROOT, args.output, source_head=args.source_head)
    print(json.dumps({
        "status": "BUILT",
        "artifact": str(args.output),
        "file_count": manifest["file_count"],
        "source_head": manifest["source_head"],
        "contains_credentials": False,
        "linux_git_required": False,
        "full_live_acceptance": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
