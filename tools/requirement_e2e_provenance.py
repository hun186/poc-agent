#!/usr/bin/env python3
"""Generate deterministic externally reviewable provenance for incremental deployments."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.runtime_provenance import RUNTIME_PATHS


def generate(repo: Path, reviewed_sha: str, output: Path) -> None:
    resolved = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{reviewed_sha}^{{commit}}"], text=True,
    ).strip()
    raw = subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-rz", "--full-tree", resolved, "--", *RUNTIME_PATHS],
    )
    files = []
    for record in raw.rstrip(b"\0").split(b"\0") if raw else []:
        header, encoded = record.split(b"\t", 1)
        _mode, kind, blob = header.decode("ascii").split()
        if kind != "blob":
            continue
        path = encoded.decode("utf-8")
        data = subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", blob])
        files.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
    value = {"repository": "hun186/poc-agent", "reviewed_runtime_sha": resolved,
             "runtime_files": sorted(files, key=lambda item: item["path"]), "schema_version": 1}
    output.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--output", type=Path, default=Path("REQUIREMENT_E2E_PROVENANCE.json"))
    args = parser.parse_args()
    generate(args.repo, args.reviewed_sha, args.output)


if __name__ == "__main__":
    main()
