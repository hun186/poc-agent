"""Bounded policy and schema for Requirement release provenance."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
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

PROVENANCE_SCHEMA_VERSION = 2
PROVENANCE_REPOSITORY = "hun186/poc-agent"
PROVENANCE_NAME = "REQUIREMENT_E2E_PROVENANCE.json"

# These are source/configuration formats for which Git's text checkout EOL
# conversion cannot change the byte meaning beyond line separators. Shell
# scripts are deliberately absent because this repository enforces eol=lf for
# *.sh. Binary Office documents, images, archives, and unknown extensions are
# raw-byte exact.
EOL_EQUIVALENT_EXTENSIONS = frozenset({
    ".cfg", ".css", ".html", ".ini", ".js", ".json", ".md", ".py",
    ".toml", ".txt", ".yaml", ".yml",
})
EOL_EQUIVALENT_FILENAMES = frozenset({"requirements.txt"})


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


def source_equivalence(reviewed: bytes, candidate: bytes, path: str) -> str | None:
    """Return the sole accepted source representation, or ``None`` on drift.

    Exact bytes always pass. Eligible text passes only when an LF-only reviewed
    blob becomes the candidate by replacing every LF byte with CRLF. No decode,
    whitespace handling, BOM handling, or final-newline special case occurs.
    """
    if reviewed == candidate:
        return "git_blob_exact"
    value = PurePosixPath(path)
    eligible = value.suffix.lower() in EOL_EQUIVALENT_EXTENSIONS or value.name in EOL_EQUIVALENT_FILENAMES
    if eligible and b"\n" in reviewed and b"\r" not in reviewed:
        if candidate == reviewed.replace(b"\n", b"\r\n"):
            return "git_blob_lf_to_worktree_crlf"
    return None


def validate_provenance(value: object) -> dict:
    """Strictly validate and canonically order schema-v2 provenance."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "repository", "reviewed_runtime_sha", "runtime_files",
    }:
        raise ValueError("release_provenance_invalid")
    if (value["schema_version"] != PROVENANCE_SCHEMA_VERSION
            or value["repository"] != PROVENANCE_REPOSITORY
            or not isinstance(value["reviewed_runtime_sha"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", value["reviewed_runtime_sha"])):
        raise ValueError("release_provenance_invalid")
    entries = value["runtime_files"]
    if not isinstance(entries, list) or not entries or len(entries) > 5000:
        raise ValueError("release_provenance_invalid")
    normalized, seen = [], set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"path", "sha256"}
                or not isinstance(entry.get("path"), str)
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or not is_runtime_provenance_path(entry["path"])
                or entry["path"] in seen):
            raise ValueError("release_provenance_invalid")
        seen.add(entry["path"])
        normalized.append({"path": entry["path"], "sha256": entry["sha256"]})
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "repository": PROVENANCE_REPOSITORY,
        "reviewed_runtime_sha": value["reviewed_runtime_sha"],
        "runtime_files": sorted(normalized, key=lambda item: item["path"]),
    }


def load_provenance(path: Path) -> dict:
    try:
        return validate_provenance(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        raise ValueError("release_provenance_invalid") from exc


def provenance_fingerprint(value: object) -> str:
    canonical = json.dumps(validate_provenance(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_package_files(root: Path, provenance: object) -> None:
    """Require exact package-byte hashes; deployment verification never normalizes."""
    value = validate_provenance(provenance)
    for entry in value["runtime_files"]:
        try:
            actual = hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError("active_runtime_source_mismatch") from exc
        if actual != entry["sha256"]:
            raise ValueError("active_runtime_source_mismatch")
