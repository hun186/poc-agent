"""Local-only A6 annotation file preparation. Never emit private text to stdout.

This command deliberately writes a private JSON file, unlike the aggregate
evaluation CLI. The operator owns the destination directory and must keep
the file off shared drives, Git, CI and application logs.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from .arc_relax_replay import prepare_relax_annotation
from .arc_semantic_eval import MAX_CASES, MAX_TOTAL_ROWS
from .arc_semantic_review import _unique_pairs

MAX_FILE_BYTES = 2 * 1024 * 1024
_USAGE = "python -m agent.es.evidence_core.arc_relax_annotation_cli PRIVATE_CASES.json PRIVATE_ANNOTATION.json"


def _emit(record, stream):
    print(json.dumps(record, sort_keys=True, separators=(",", ":")), file=stream)


def _load(path):
    # Nonblocking open + descriptor inspection reject pipes/devices without
    # waiting on a writer. Local trusted filesystem; no remote IO.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("not_regular_file")
        raw = source.read(MAX_FILE_BYTES + 1)
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("input_size")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        print(_USAGE)
        return 0
    if len(args) != 2:
        _emit({"status": "INVALID_ARGUMENTS", "usage": _USAGE}, sys.stderr)
        return 2
    try:
        cases = _load(Path(args[0]))
        if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
            raise ValueError("invalid_cases")
        prepared = []
        row_count = 0
        for case in cases:
            template = prepare_relax_annotation(case)
            if template is None:
                raise ValueError("invalid_case")
            row_count += len(template["rows"])
            if row_count > MAX_TOTAL_ROWS:
                raise ValueError("too_many_rows")
            prepared.append({"case": case,
                             "fixture_digest": template["fixture_digest"],
                             "labels": template["rows"]})
        encoded = (json.dumps(prepared, ensure_ascii=False, indent=2,
                              allow_nan=False) + "\n").encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError("output_size")
    except (OSError, ValueError, TypeError, RecursionError):
        _emit({"status": "INVALID_OR_UNREADABLE_FIXTURE"}, sys.stderr)
        return 2
    try:
        # O_EXCL refuses existing files, directories, and symlinks. On
        # POSIX the initial mode permits only the owner. Windows inherits
        # the destination directory's ACL; it must already be private.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        fd = os.open(Path(args[1]), flags, 0o600)
    except OSError:
        _emit({"status": "OUTPUT_NOT_CREATED"}, sys.stderr)
        return 2
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(encoded)
            target.flush()
    except OSError:
        # Never overwrite or delete another path on a write failure.
        _emit({"status": "OUTPUT_WRITE_FAILED_MAY_BE_PARTIAL"}, sys.stderr)
        return 2
    _emit({"status": "PRIVATE_ANNOTATION_CREATED", "cases": len(prepared),
           "rows_to_label": row_count}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
