"""Safety and evidence primitives for the deployment-host Requirement E2E harness."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import stat
import tempfile
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from dotenv import dotenv_values

from python_compat import StrEnum


fcntl = importlib.import_module("fcntl") if importlib.util.find_spec("fcntl") is not None else None
msvcrt = importlib.import_module("msvcrt") if importlib.util.find_spec("msvcrt") is not None else None

CANONICAL_SOURCE_SHA256 = "2d50bed20a3e697020107ece218e7c001580e1df03adc1c30f8060c4e9118d03"


class StageStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REACHED = "NOT_REACHED"


class ExitCode(IntEnum):
    PASS = 0
    PREFLIGHT = 2
    FUNCTIONAL = 3
    INTERNAL = 4
    CLEANUP = 5


STAGES = (
    "CONFIG_PREFLIGHT", "API_READINESS", "AUTH", "PIPELINE_READINESS", "RUNTIME_WORKERS",
    "INPUT_VALIDATION", "FIXTURE_PROFILE", "FIXTURE_SOURCE", "REQUIREMENT_PREVIEW",
    "REQUIREMENT_IMPORT", "SNAPSHOT", "REQUIREMENT_ITEMS", "SCHEDULE_FIXTURE",
    "SCHEDULE_VERSION", "SCHEDULE_APPROVE", "SCHEDULE_ENABLE", "AUTO_CLAIM", "RUN_IDENTITY",
    "RUN_SELECTION", "NEXT_RUN_ADVANCE", "HANDOFF", "REPORT_JOBS", "REMOTE_EXECUTION",
    "ARTIFACT_RECONCILIATION", "RUN_ITEMS_TERMINAL", "BATCH_TERMINAL", "DOCX_INTEGRITY",
    "SHA256_MATCH", "CLEANUP", "FINAL_EVIDENCE",
)


class HarnessFailure(RuntimeError):
    def __init__(self, category: str, *, stage: str | None = None, exit_code: ExitCode = ExitCode.FUNCTIONAL):
        super().__init__(category)
        self.category, self.stage, self.exit_code = category, stage, exit_code


def validate_live_platform(mode: str = "local") -> None:
    """Fail closed unless this live harness has all Linux host primitives."""
    if mode == "remote":
        return
    if not (
        sys.platform.startswith("linux")
        and os.name == "posix"
        and Path("/proc").is_dir()
        and callable(getattr(os, "geteuid", None))
        and fcntl is not None
    ):
        raise HarnessFailure(
            "unsupported_local_platform", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT,
        )


@dataclass(frozen=True)
class E2EConfig:
    mode: str
    base_url: str
    model: str
    artifact_root: Path | None
    token: str | None
    username: str | None
    password: str | None
    output_dir: Path
    profile_name: str
    source_name: str
    schedule_name: str
    expected_source_sha: str | None
    expected_runtime_sha: str | None
    api_log_path: Path
    schedule_log_path: Path
    handoff_log_path: Path
    anchor_lead_seconds: int = 120
    allowed_anchor_window_seconds: int = 300
    auto_claim_timeout_seconds: int = 210
    handoff_timeout_seconds: int = 120
    remote_timeout_seconds: int = 1800
    reconcile_timeout_seconds: int = 180
    exit_code_for_failure: ExitCode = ExitCode.PREFLIGHT

    @classmethod
    def from_environment(
        cls, env: dict[str, str], mode: str = "local",
        *, production_artifact_root: Path | str | None = None,
    ) -> "E2EConfig":
        def required(name: str) -> str:
            value = (env.get(name) or "").strip()
            if not value:
                raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
            return value

        token = (env.get("SRA_E2E_EDITOR_TOKEN") or "").strip() or None
        username = (env.get("SRA_E2E_EDITOR_USERNAME") or "").strip() or None
        password = (env.get("SRA_E2E_EDITOR_PASSWORD") or "").strip() or None
        if bool(token) == bool(username and password) or bool(username) != bool(password):
            raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
        def positive(name: str, default: int) -> int:
            try: value = int(env.get(name, str(default)))
            except ValueError: value = 0
            if value <= 0: raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
            return value
        def optional_sha(name: str, length: int) -> str | None:
            value = (env.get(name) or "").strip()
            if value and not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
                raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
            return value or None
        artifact_value = (env.get("SRA_E2E_REQUIREMENT_ARTIFACT_ROOT") or "").strip()
        production_artifact_value = str(production_artifact_root or "").strip()
        artifact_root = None
        if mode == "local":
            selected_artifact_value = artifact_value or production_artifact_value
            if not selected_artifact_value:
                raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
            artifact_root = Path(selected_artifact_value).expanduser().resolve(strict=False)
            if artifact_value and production_artifact_value:
                production_root = Path(production_artifact_value).expanduser().resolve(strict=False)
                if artifact_root != production_root:
                    raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
        elif artifact_value:
            artifact_root = Path(artifact_value)
        runtime_sha = optional_sha("SRA_E2E_EXPECTED_RUNTIME_SHA", 40)
        return cls(
            mode=mode,
            base_url=(env.get("SRA_E2E_BASE_URL") or "http://127.0.0.1:9002").rstrip("/"),
            model=required("SRA_E2E_MODEL"), artifact_root=artifact_root,
            token=token, username=username, password=password,
            output_dir=Path(env.get("SRA_E2E_OUTPUT_DIR") or "operator_e2e/output/requirement_e2e"),
            profile_name=env.get("SRA_E2E_PROFILE_NAME") or "SRA Requirement Operator E2E Profile v1",
            source_name=env.get("SRA_E2E_SOURCE_NAME") or "SRA Requirement Operator E2E Source v1",
            schedule_name=env.get("SRA_E2E_SCHEDULE_NAME") or "SRA Requirement Operator E2E Schedule v1",
            expected_source_sha=optional_sha("SRA_E2E_EXPECTED_SOURCE_SHA", 64),
            expected_runtime_sha=runtime_sha,
            api_log_path=Path(env.get("SRA_E2E_API_LOG_PATH") or "SRA-API_output.txt"),
            schedule_log_path=Path(env.get("SRA_E2E_SCHEDULE_LOG_PATH") or "SRA-ScheduleWorker_output.txt"),
            handoff_log_path=Path(env.get("SRA_E2E_HANDOFF_LOG_PATH") or "SRA-HandoffWorker_output.txt"),
            anchor_lead_seconds=positive("SRA_E2E_ANCHOR_LEAD_SECONDS", 120),
            allowed_anchor_window_seconds=positive("SRA_E2E_ALLOWED_ANCHOR_WINDOW_SECONDS", 300),
            auto_claim_timeout_seconds=positive("SRA_E2E_AUTO_CLAIM_TIMEOUT_SECONDS", 210),
            handoff_timeout_seconds=positive("SRA_E2E_HANDOFF_TIMEOUT_SECONDS", 120),
            remote_timeout_seconds=positive("SRA_E2E_REMOTE_TIMEOUT_SECONDS", 1800),
            reconcile_timeout_seconds=positive("SRA_E2E_RECONCILE_TIMEOUT_SECONDS", 180),
        )


def load_e2e_environment(path: Path, process_env: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for key, value in dotenv_values(path).items():
            if not key.startswith("SRA_E2E_"):
                raise HarnessFailure("configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
            if value is not None: values[key] = value
    values.update({key: value for key, value in process_env.items() if key.startswith("SRA_E2E_")})
    return values


def has_usable_requirement_process_configuration(
    process_env: dict[str, str], mode: str = "local",
    *, production_artifact_root: Path | str | None = None,
) -> bool:
    """Return whether process variables alone can construct Requirement E2E config."""
    requirement_env = {
        key: value for key, value in process_env.items() if key.startswith("SRA_E2E_")
    }
    try:
        E2EConfig.from_environment(
            requirement_env, mode, production_artifact_root=production_artifact_root,
        )
    except HarnessFailure:
        return False
    return True


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;\"']+"),
    re.compile(r"(?i)(bearer\s+)[^\s,;\"']+"),
    re.compile(r"(?i)((?:password|token|secret|service[_ ]?key|connection[_ ]?string|pwd|user\s+id)\s*[:=]\s*)[^\s,;\"']+"),
)


def redact(value: Any, known_secrets: Iterable[str] = ()) -> Any:
    def clean(text: str) -> str:
        for secret in sorted({item for item in known_secrets if item}, key=len, reverse=True):
            text = text.replace(secret, "<REDACTED>")
        for pattern in _SECRET_PATTERNS: text = pattern.sub(r"\1<REDACTED>", text)
        return text
    if isinstance(value, dict):
        return {key: ("<REDACTED>" if re.search(r"(?i)authorization|password|token|secret|service.?key|connection.?string|^pwd$|user.?id", str(key)) else redact(item, known_secrets)) for key, item in value.items()}
    if isinstance(value, list): return [redact(item, known_secrets) for item in value]
    if isinstance(value, tuple): return tuple(redact(item, known_secrets) for item in value)
    return clean(value) if isinstance(value, str) else value


def result_document(run_id: str, execution_mode: str = "local") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {"schema_version": "requirement_e2e_result_v2", "execution_mode": execution_mode,
            "e2e_run_id": run_id, "started_at": now,
            "finished_at": None, "duration_seconds": None, "overall_status": "FAIL", "exit_code": int(ExitCode.INTERNAL),
            "failed_stage": None, "failure_category": None, "operator_source": {},
            "deployment_source": {}, "deployment_evidence": {}, "input": {}, "fixtures": {},
            "requirement_import": {}, "schedule": {}, "batch": {}, "items": [], "artifacts": [],
            "stages": [{"name": name, "status": StageStatus.NOT_REACHED} for name in STAGES], "warnings": []}


def atomic_write_json(path: Path, value: Any, *, overwrite: bool = False) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", overwrite=overwrite)


def atomic_write_text(path: Path, value: str, *, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite: raise FileExistsError(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True); raise


class SingleRunLock:
    def __init__(self, path: Path, mode: str = "local"): self.path, self.mode, self.stream = path, mode, None
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True); self.stream = self.path.open("a+")
        try:
            if os.name == "nt" and self.mode == "remote":
                if msvcrt is None: raise OSError("msvcrt unavailable")
                self.stream.seek(0); self.stream.write("0"); self.stream.flush(); self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                if fcntl is None: raise OSError("fcntl unavailable")
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc: raise HarnessFailure("concurrent_e2e_run", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT) from exc
        return self
    def __exit__(self, *_):
        if self.stream:
            if os.name == "nt" and self.mode == "remote" and msvcrt is not None:
                self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None: fcntl.flock(self.stream, fcntl.LOCK_UN)
            self.stream.close()


def choose_fixture(items: list[dict[str, Any]], exact: Callable[[dict[str, Any]], bool]):
    if not items: return "create", None
    matches = [item for item in items if exact(item)]
    if len(items) > 1 or len(matches) > 1: raise HarnessFailure("fixture_ambiguous")
    if not matches: raise HarnessFailure("fixture_drift")
    return "reuse", matches[0]


def recover_ambiguous_write(reread: Callable[[], list[dict[str, Any]]]):
    winners = reread()
    if len(winners) > 1: raise HarnessFailure("ambiguous_write")
    return winners[0] if winners else None


def validate_preview(value: dict[str, Any]) -> None:
    if value.get("has_errors") or value.get("accepted_count") != 3 or value.get("rejected_count") != 0:
        raise HarnessFailure("preview_rejected", stage="REQUIREMENT_PREVIEW")


def _iso(value: Any) -> datetime:
    if isinstance(value, datetime): result = value
    else: result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None: raise HarnessFailure("automatic_claim_identity_mismatch")
    return result.astimezone(timezone.utc)


def classify_new_batch(runs: list[dict[str, Any]], baseline_ids: set[str], version_id: str, snapshot_id: str, scheduled_for: str):
    new = [run for run in runs if run.get("batch_run_id") not in baseline_ids]
    scheduled = [run for run in new if run.get("trigger_type") == "scheduled" and run.get("schedule_version_id") == version_id and _iso(run.get("scheduled_for")) == _iso(scheduled_for)]
    if len(scheduled) > 1: raise HarnessFailure("multiple_scheduled_runs", stage="AUTO_CLAIM")
    if not scheduled:
        if new: raise HarnessFailure("automatic_claim_identity_mismatch", stage="RUN_IDENTITY")
        raise HarnessFailure("automatic_claim_timeout", stage="AUTO_CLAIM")
    run = scheduled[0]
    if run.get("snapshot_id") != snapshot_id: raise HarnessFailure("snapshot_identity_mismatch", stage="RUN_IDENTITY")
    if run.get("selected_count") != 3 or run.get("skipped_count") != 0: raise HarnessFailure("item_count_mismatch", stage="RUN_SELECTION")
    return run


def validate_next_run(scheduled_for: Any, advanced_next_run_at: Any) -> None:
    scheduled, advanced = _iso(scheduled_for), _iso(advanced_next_run_at)
    if advanced <= scheduled or advanced != scheduled + timedelta(minutes=10080):
        raise HarnessFailure("automatic_claim_identity_mismatch", stage="NEXT_RUN_ADVANCE")


def validate_remote_items(items: list[dict[str, Any]]) -> None:
    selected = [item for item in items if item.get("selection_status") == "selected"]
    identifiers = [item.get("remote_job_id") for item in selected]
    if len(selected) != 3 or any(not item for item in identifiers) or len(set(identifiers)) != 3:
        raise HarnessFailure("remote_job_count_mismatch", stage="REPORT_JOBS")


def terminal_failure(batch: dict[str, Any]) -> str | None:
    for item in batch.get("items", []):
        if item.get("remote_job_state") in {"failed", "recovery_required", "expired"} or item.get("execution_state") in {"failed", "recovery_required", "expired"}:
            return "remote_execution_failed"
    if batch.get("state") in {"failed", "completed_with_failures", "recovery_required"}: return "batch_terminal_failure"
    return None


def validate_terminal(batch: dict[str, Any]) -> None:
    failure = terminal_failure(batch)
    if failure: raise HarnessFailure(failure, stage="REMOTE_EXECUTION" if failure == "remote_execution_failed" else "BATCH_TERMINAL")
    items = [item for item in batch.get("items", []) if item.get("selection_status") == "selected"]
    if len(items) != 3 or any(item.get("remote_job_state") != "completed" or item.get("execution_state") != "completed" for item in items):
        raise HarnessFailure("remote_execution_timeout", stage="REMOTE_EXECUTION")
    if batch.get("state") != "completed" or batch.get("success_count") != 3 or batch.get("failure_count") != 0:
        raise HarnessFailure("batch_terminal_failure", stage="BATCH_TERMINAL")


def output_root_fingerprint(root: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(root.expanduser().resolve(strict=False))).encode()).hexdigest()


def validate_artifact(root: Path, persisted_root_fingerprint: str, relative_path: str, persisted_sha256: str, copy_to: Path):
    root = root.expanduser().resolve(strict=False)
    if output_root_fingerprint(root) != persisted_root_fingerprint: raise HarnessFailure("artifact_root_fingerprint_mismatch", stage="ARTIFACT_RECONCILIATION")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".docx": raise HarnessFailure("artifact_invalid", stage="DOCX_INTEGRITY")
    source = (root / Path(*relative.parts)).resolve(strict=False)
    if root not in source.parents or not source.is_file() or source.is_symlink(): raise HarnessFailure("artifact_missing", stage="ARTIFACT_RECONCILIATION")
    try:
        with zipfile.ZipFile(source) as package:
            names = package.namelist()
            if "[Content_Types].xml" not in names or "word/document.xml" not in names: raise ValueError
            if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names): raise ValueError
            if package.testzip() is not None: raise ValueError
    except (OSError, ValueError, zipfile.BadZipFile) as exc: raise HarnessFailure("artifact_invalid", stage="DOCX_INTEGRITY") from exc
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", str(persisted_sha256)) or actual != persisted_sha256:
        raise HarnessFailure("artifact_sha256_mismatch", stage="SHA256_MATCH")
    copy_to.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, copy_to.open("xb") as outgoing: shutil.copyfileobj(incoming, outgoing)
    return {"relative_path": relative.as_posix(), "persisted_sha256": persisted_sha256, "actual_sha256": actual, "evidence_path": str(copy_to)}


def validate_downloaded_artifact(data: bytes, filename: str, persisted_sha256: str, copy_to: Path):
    """Independently validate and retain bytes returned by the existing Report Job API."""
    name = PurePosixPath(filename)
    if name.is_absolute() or ".." in name.parts or len(name.parts) != 1 or name.suffix.lower() != ".docx":
        raise HarnessFailure("artifact_invalid", stage="DOCX_INTEGRITY")
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names = package.namelist()
            if "[Content_Types].xml" not in names or "word/document.xml" not in names: raise ValueError
            if any(PurePosixPath(item).is_absolute() or ".." in PurePosixPath(item).parts for item in names): raise ValueError
            if package.testzip() is not None: raise ValueError
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HarnessFailure("artifact_invalid", stage="DOCX_INTEGRITY") from exc
    actual = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", str(persisted_sha256)) or actual != persisted_sha256:
        raise HarnessFailure("artifact_sha256_mismatch", stage="SHA256_MATCH")
    copy_to.parent.mkdir(parents=True, exist_ok=True)
    with copy_to.open("xb") as stream: stream.write(data)
    return {"filename": name.name, "persisted_sha256": persisted_sha256, "actual_sha256": actual,
            "evidence_path": str(copy_to)}


def _proc_start_time(pid: int) -> str: return Path(f"/proc/{pid}/stat").read_text().split()[21]
def _proc_uid(pid: int) -> int:
    line = next(line for line in Path(f"/proc/{pid}/status").read_text().splitlines() if line.startswith("Uid:"))
    return int(line.split()[2])
def _proc_cwd(pid: int) -> Path: return Path(f"/proc/{pid}/cwd").resolve()
def _proc_cmdline(pid: int) -> str: return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")


def verify_worker_identity(path: Path, role: str, project_root: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid(): raise ValueError
        values = dict(line.split("=", 1) for line in path.read_text().splitlines())
        if set(values) != {"role", "pid", "process_start_time"} or values["role"] != role: raise ValueError
        pid = int(values["pid"])
        if (_proc_start_time(pid) != values["process_start_time"] or _proc_uid(pid) != os.geteuid()
                or _proc_cwd(pid) != project_root.resolve()): raise ValueError
        command = _proc_cmdline(pid)
        if "requirement_scheduler.cli" not in command or f"{role}-worker" not in command: raise ValueError
        return {"role": role, "pid": pid, "process_start_time": values["process_start_time"], "alive": True}
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise HarnessFailure("worker_unavailable", stage="RUNTIME_WORKERS", exit_code=ExitCode.PREFLIGHT) from exc


def bounded_log_tail(path: Path, known_secrets: Iterable[str], *, max_lines: int = 100, max_bytes: int = 65536) -> str:
    if not path.is_file() or path.is_symlink(): return ""
    data = path.read_bytes()[-max_bytes:].decode("utf-8", errors="replace")
    return redact("\n".join(data.splitlines()[-max_lines:]), known_secrets)
