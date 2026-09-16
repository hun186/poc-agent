"""Bounded source paths that form Requirement deployment runtime authority."""
from __future__ import annotations

from pathlib import PurePosixPath


RUNTIME_ROOTS = (
    "agent",
    "api",
    "batch_scheduler",
    "config",
    "data_ingestion",
    "operator_e2e",
    "requirement_scheduler",
    "shared",
    "sra_api",
)

# Root files are selected individually: these are imported source, runtime
# dependency authority, or deployment entrypoints/supervision.  In particular,
# the empty root __init__.py and repository documentation are not runtime input.
RUNTIME_FILES = (
    "app.py",
    "python_compat.py",
    "requirements.txt",
    "run_sra_api.sh",
    "telemetry.py",
)

RUNTIME_PATHS = RUNTIME_ROOTS + RUNTIME_FILES


def is_runtime_provenance_path(path: str) -> bool:
    """Return whether a normalized repository-relative path is in policy."""
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return False
    return path in RUNTIME_FILES or relative.parts[0] in RUNTIME_ROOTS
