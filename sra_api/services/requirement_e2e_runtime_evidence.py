"""Safe, read-only deployment-host evidence for remote Requirement acceptance."""
from __future__ import annotations

import hashlib
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath

from operator_e2e.requirement_e2e_support import output_root_fingerprint, verify_worker_identity
from shared.runtime_provenance import (
    PROVENANCE_NAME,
    RUNTIME_ROOTS,
    is_project_module_name,
    load_provenance,
    provenance_fingerprint,
    verify_package_files,
)

_MANAGED_TOP_LEVEL = set(RUNTIME_ROOTS)


def _active_project_modules(project_root: Path) -> list[tuple[str, Path]]:
    modules = []
    for module_name, module in tuple(sys.modules.items()):
        value = getattr(module, "__file__", None)
        if value and is_project_module_name(module_name):
            path = Path(value).resolve(strict=False)
            modules.append((module_name, path))
    # The workers are positively bound to this entrypoint by verify_worker_identity.
    modules.append(("requirement_scheduler.cli",
                    (project_root / "requirement_scheduler" / "cli.py").resolve(strict=False)))
    return sorted(set(modules), key=lambda item: (item[0], str(item[1])))


def _module_name_for_test_path(project_root: Path, path: Path) -> str:
    """Derive a module name for the legacy explicit-path test seam only."""
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(project_root)
        parts = relative.parts
    except ValueError:
        parts = resolved.parts
        indexes = [index for index, part in enumerate(parts) if part in _MANAGED_TOP_LEVEL]
        if indexes:
            parts = parts[indexes[-1]:]
        else:
            parts = (resolved.name,)
    without_suffix = Path(*parts).with_suffix("").parts
    return ".".join(part for part in without_suffix if part != "__init__")


def collect_source_evidence(project_root: Path, *, active_paths: list[Path] | None = None) -> dict:
    """Verify bounded active/runtime-critical bytes; ignore inactive overlay residue."""
    project_root = project_root.resolve()
    provenance_path = project_root / PROVENANCE_NAME
    if not provenance_path.is_file():
        raise RuntimeError("release_provenance_missing")
    try:
        provenance = load_provenance(provenance_path)
        verify_package_files(project_root, provenance)
    except ValueError as exc:
        category = str(exc)
        if category == "active_runtime_source_mismatch":
            raise RuntimeError(category) from exc
        raise RuntimeError("release_provenance_invalid") from exc
    expected = {entry["path"]: entry["sha256"] for entry in provenance["runtime_files"]}

    active = (
        [(_module_name_for_test_path(project_root, Path(path)), Path(path)) for path in active_paths]
        if active_paths is not None
        else _active_project_modules(project_root)
    )
    active_relative = []
    for module_name, path in active:
        resolved = Path(path).resolve(strict=False)
        try:
            relative = resolved.relative_to(project_root).as_posix()
        except ValueError as exc:
            if is_project_module_name(module_name):
                raise RuntimeError("runtime_module_shadowing") from exc
            continue
        if relative.endswith((".pyc", ".pyo")):
            source = Path(relative.replace("/__pycache__/", "/")).with_name(Path(relative).name.split(".")[0] + ".py").as_posix()
            relative = source
        if relative not in expected:
            raise RuntimeError("unexpected_active_runtime_module")
        active_relative.append(relative)

    residual = 0
    for top in _MANAGED_TOP_LEVEL:
        root = project_root / top
        if root.is_dir():
            residual += sum(1 for path in root.rglob("*.py")
                            if "__pycache__" not in path.parts and path.relative_to(project_root).as_posix() not in expected)
    return {
        "identity_kind": "incremental_package", "identity_verified": True,
        "reviewed_runtime_sha": provenance["reviewed_runtime_sha"],
        "provenance_fingerprint": provenance_fingerprint(provenance),
        "runtime_files": [{"path": path, "sha256": expected[path]} for path in sorted(expected)],
        "active_runtime_files": sorted(set(active_relative)),
        "inactive_residual_count": residual,
        "warnings": ["inactive_residual_files_present"] if residual else [],
    }


def collect_runtime_evidence(project_root: Path, artifact_root: Path) -> dict:
    workers = {}
    for role in ("schedule", "handoff"):
        try:
            verify_worker_identity(project_root / f".run_sra_api_{role}.identity", role, project_root)
            workers[role] = {"alive": True, "identity_verified": True}
        except Exception:
            workers[role] = {"alive": False, "identity_verified": False}
    return {
        "schema_version": "requirement_e2e_runtime_evidence_v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "deployment_source": collect_source_evidence(project_root),
        "workers": workers,
        "artifact_root_fingerprint": output_root_fingerprint(artifact_root),
    }


def configured_runtime_evidence(project_root: Path) -> dict:
    root = os.getenv("REQUIREMENT_HANDOFF_OUTPUT_ROOT", "").strip()
    if not root: raise RuntimeError("requirement_handoff_output_root_unavailable")
    return collect_runtime_evidence(project_root, Path(root))


class ArtifactEvidenceError(RuntimeError):
    pass


def configured_published_artifact(store, batch_run_id: str, run_item_id: str) -> bytes:
    """Return bytes only after durable identity, root, DOCX, and digest validation."""
    root_value = os.getenv("REQUIREMENT_HANDOFF_OUTPUT_ROOT", "").strip()
    if not root_value:
        raise ArtifactEvidenceError("requirement_handoff_output_root_unavailable")
    try:
        evidence = store.get_operator_artifact_evidence(
            batch_run_id=batch_run_id, run_item_id=run_item_id,
        )
    except KeyError as exc:
        raise ArtifactEvidenceError("artifact_missing") from exc

    if (evidence.get("selection_status") != "selected" or not evidence.get("remote_job_id")
            or not evidence.get("artifact_relative_path")
            or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("artifact_sha256") or ""))):
        raise ArtifactEvidenceError("artifact_metadata_missing")

    root = Path(root_value).expanduser().resolve(strict=False)
    if output_root_fingerprint(root) != evidence.get("phase1a_output_root_fingerprint"):
        raise ArtifactEvidenceError("artifact_root_fingerprint_mismatch")
    relative = PurePosixPath(evidence["artifact_relative_path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".docx":
        raise ArtifactEvidenceError("artifact_invalid")
    unresolved = root / Path(*relative.parts)
    resolved = unresolved.resolve(strict=False)
    if root not in resolved.parents or unresolved.is_symlink() or not resolved.is_file():
        raise ArtifactEvidenceError("artifact_missing")
    try:
        data = resolved.read_bytes()
        with zipfile.ZipFile(BytesIO(data)) as package:
            names = package.namelist()
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError
            if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names):
                raise ValueError
            if package.testzip() is not None:
                raise ValueError
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ArtifactEvidenceError("artifact_invalid") from exc
    if hashlib.sha256(data).hexdigest() != evidence["artifact_sha256"]:
        raise ArtifactEvidenceError("artifact_sha256_mismatch")
    return data
