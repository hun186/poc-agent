"""Bounded policy and schema for Requirement release provenance."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
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
UNEXPECTED_RUNTIME_INPUT = "unexpected_runtime_input"

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


def _resolve_selector_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def manual_synonym_files(root: Path, environ: Mapping[str, str] | None = None) -> list[Path]:
    """Reproduce manual.py's direct-child, case-insensitive JSON membership."""
    env = os.environ if environ is None else environ
    configured = env.get("MANUAL_SYNONYMS_DIR", "config/synonyms")
    # Preserve the loader's historical opt-out: an explicitly empty value is
    # not a relative path selecting the project root.
    if configured == "":
        return []
    directory = _resolve_selector_path(root, configured)
    if not directory.is_dir():
        return []
    try:
        return [directory / name for name in os.listdir(directory)
                if name.lower().endswith(".json")]
    except OSError:
        return []


def index_config_paths(root: Path, environ: Mapping[str, str] | None = None, *,
                       selector_base: Path | None = None) -> list[Path]:
    """Return index_loader candidates with its existing selector precedence."""
    env = os.environ if environ is None else environ
    single = env.get("INDEXES_CONFIG") or env.get("INDEX_CONFIG")
    multi = env.get("INDEXES_CONFIGS")
    selected = single or multi
    if selected:
        normalized = selected.replace(",", os.pathsep)
        base = root if selector_base is None else selector_base
        return [_resolve_selector_path(base, item) for item in normalized.split(os.pathsep) if item.strip()]
    app_env = env.get("APP_ENV") or env.get("ENV") or env.get("PY_ENV") or ""
    paths = [root / "config/indexes.yaml"]
    if app_env:
        paths.append(root / f"config/indexes.{app_env}.yaml")
    return [path.resolve(strict=False) for path in paths]


def requirement_sql_registry_path(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return _resolve_selector_path(
        root, env.get("REQUIREMENT_SQL_REGISTRY_FILE", "config/requirements/sql_registry.json")
    )


def requirement_sql_registry_repository_path(
    root: Path, environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return the selected registry's repository-relative member, when local."""
    resolved_root = root.resolve(strict=False)
    try:
        return requirement_sql_registry_path(resolved_root, environ).relative_to(
            resolved_root
        ).as_posix()
    except ValueError:
        return None


def editor_form_config_path(root: Path, environ: Mapping[str, str] | None = None, *,
                            selector_base: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("SRA_EDITOR_FORM_CONFIG")
    if configured:
        return _resolve_selector_path(root if selector_base is None else selector_base, configured)
    return _resolve_selector_path(root, "config/editor_form.default.json")


def discover_release_runtime_inputs(
    root: Path, environ: Mapping[str, str] | None = None,
) -> list[Path]:
    """Discover only bounded release-managed inputs that runtime would consume.

    Missing candidates are not inputs. Existing selected external paths remain in
    the result so provenance acceptance fails closed rather than silently
    treating arbitrary external bytes as attested.
    """
    root = root.resolve(strict=False)
    paths = manual_synonym_files(root, environ)
    paths.extend(path for path in index_config_paths(root, environ) if path.is_file())
    editor_form = editor_form_config_path(root, environ)
    if editor_form.is_file():
        paths.append(editor_form)
    return sorted(set(path.resolve(strict=False) for path in paths), key=str)


def verify_discovered_runtime_inputs(root: Path, provenance: object,
                                     environ: Mapping[str, str] | None = None) -> None:
    """Require every actually selected release input to belong to provenance."""
    root = root.resolve(strict=False)
    expected = {entry["path"] for entry in validate_provenance(provenance)["runtime_files"]}
    for path in discover_release_runtime_inputs(root, environ):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(UNEXPECTED_RUNTIME_INPUT) from exc
        if relative not in expected:
            raise ValueError(UNEXPECTED_RUNTIME_INPUT)


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


def verify_package_files(
    root: Path, provenance: object, *, selected_registry: str | None = None,
) -> None:
    """Require exact package-byte hashes; deployment verification never normalizes.

    ``selected_registry`` is deliberately explicit: only the deployment host is
    authoritative for the Requirement SQL registry selection. Generic package
    verification, including remote-operator preflight, must not infer that
    deployment-local identity from its own process environment.
    """
    value = validate_provenance(provenance)
    if selected_registry is not None and any(
        entry["path"] == selected_registry for entry in value["runtime_files"]
    ):
        # The selected registry is deployment-local authority. Reject before
        # reading its bytes, and never include its identity in the failure.
        raise ValueError("release_provenance_invalid")
    for entry in value["runtime_files"]:
        try:
            actual = hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError("active_runtime_source_mismatch") from exc
        if actual != entry["sha256"]:
            raise ValueError("active_runtime_source_mismatch")
    verify_discovered_runtime_inputs(root, value)
