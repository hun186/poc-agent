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

# Only importable root Python files define top-level module names.  Runtime
# inputs such as the launcher and requirements lock are provenance-managed
# bytes, but can never identify a loaded Python module.
ROOT_PYTHON_MODULES = tuple(
    PurePosixPath(path).stem for path in RUNTIME_FILES if path.endswith(".py")
)
PROJECT_MODULE_NAMESPACES = RUNTIME_ROOTS


def is_generated_non_runtime_path(path: str) -> bool:
    """Classify generated harness/report products that never carry runtime authority."""
    value = PurePosixPath(path)
    parts = value.parts
    if len(parts) >= 2 and parts[:2] == ("operator_e2e", "output"):
        return True
    if len(parts) >= 2 and parts[0] in {"tests", "tests_code"} and "output" in parts[1:]:
        return True
    # Root-level operator DOCX files are report products, not templates.  Keep
    # nested input fixtures and all actual Python/configuration files managed.
    return len(parts) == 2 and parts[0] == "operator_e2e" and value.suffix.lower() == ".docx"


def is_project_module_name(module_name: str) -> bool:
    """Return whether an exact Python import namespace belongs to this project."""
    top_level = module_name.partition(".")[0]
    return top_level in PROJECT_MODULE_NAMESPACES or module_name in ROOT_PYTHON_MODULES


def is_runtime_provenance_path(path: str) -> bool:
    """Return whether a normalized repository-relative path is in policy."""
    relative = PurePosixPath(path)
    if (relative.is_absolute() or ".." in relative.parts or not relative.parts
            or relative.as_posix() != path or is_generated_non_runtime_path(path)):
        return False
    return path in RUNTIME_FILES or relative.parts[0] in RUNTIME_ROOTS
