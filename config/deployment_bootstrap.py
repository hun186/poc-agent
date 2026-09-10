"""Fail-closed provisioning for the launcher-owned Requirement Handoff identity."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from config.bootstrap import bootstrap_env
from data_ingestion.requirements.connections import SqlRegistry
from requirement_scheduler.config import RequirementHandoffConfig
from sra_api.security.scopes import REPORT_JOB_CREATE, REPORT_JOB_DOWNLOAD, REPORT_JOB_READ
from sra_api.security.service_key_store import ServiceKeyStore
from sra_api.security.signed_urls import validate_signing_config


STATE_VERSION = "1"
KEY_NAME = "requirement-handoff-runtime"
KEY_SCOPES = frozenset({REPORT_JOB_CREATE, REPORT_JOB_READ, REPORT_JOB_DOWNLOAD})
STATE_FILENAME = "requirement_handoff.env"
REPAIR_JOURNAL_FILENAME = "requirement_handoff.repair.json"
STATE_KEYS = (
    "SRA_BOOTSTRAP_STATE_VERSION", "SRA_BOOTSTRAP_HANDOFF_KEY_ID",
    "REQUIREMENT_HANDOFF_API_BASE_URL", "REQUIREMENT_HANDOFF_ALLOW_INSECURE_LOCALHOST",
    "REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL", "REQUIREMENT_HANDOFF_OUTPUT_ROOT",
    "REQUIREMENT_HANDOFF_CREDENTIAL_ENV", "REQUIREMENT_HANDOFF_CREDENTIAL",
)


class DeploymentBootstrapError(RuntimeError):
    """A safe, non-secret deployment bootstrap failure."""


def _fail(reason: str) -> DeploymentBootstrapError:
    return DeploymentBootstrapError(f"deployment_bootstrap_error:{reason}")


def _secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise _fail("state_directory_symlink")
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise _fail("state_directory_invalid")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise _fail("state_directory_mode")


def _read_state(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise _fail("state_file_symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise _fail("state_file_invalid")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise _fail("state_file_mode")
    try:
        raw = path.read_bytes()
        if b"\0" in raw or b"\r" in raw:
            raise ValueError
        result: dict[str, str] = {}
        for line in raw.decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator != "=" or key not in STATE_KEYS or key in result or "\n" in value:
                raise ValueError
            result[key] = value
        if set(result) != set(STATE_KEYS) or result["SRA_BOOTSTRAP_STATE_VERSION"] != STATE_VERSION:
            raise ValueError
        return result
    except DeploymentBootstrapError:
        raise
    except Exception as exc:
        raise _fail("state_file_corrupt") from exc


def _write_state(path: Path, values: dict[str, str]) -> None:
    if any("\n" in value or "\r" in value or "\0" in value for value in values.values()):
        raise _fail("state_value_invalid")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for key in STATE_KEYS:
                stream.write(f"{key}={values[key]}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_repair_journal(path: Path, old_key_id: str, new_key_id: str) -> None:
    """Durably record the two identities authorized for repair recovery."""
    payload = json.dumps({
        "version": 1,
        "old_key_id": old_key_id,
        "new_key_id": new_key_id,
    }, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_repair_journal(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise _fail("repair_journal_symlink")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
            stat.S_IMODE(info.st_mode) != 0o600):
        raise _fail("repair_journal_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (set(value) != {"version", "old_key_id", "new_key_id"} or value["version"] != 1 or
                not all(isinstance(value[key], str) and value[key] for key in ("old_key_id", "new_key_id")) or
                value["old_key_id"] == value["new_key_id"]):
            raise ValueError
        return value
    except DeploymentBootstrapError:
        raise
    except Exception as exc:
        raise _fail("repair_journal_corrupt") from exc


def _remove_repair_journal(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise _fail("repair_journal_symlink")
        path.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _validate_site(project_root: Path) -> None:
    registry_path = Path(os.getenv("REQUIREMENT_SQL_REGISTRY_FILE", "config/requirements/sql_registry.json"))
    if not registry_path.is_absolute():
        registry_path = project_root / registry_path
    registry = SqlRegistry.load(registry_path)
    connection_name = os.getenv("REQUIREMENT_CONTROL_DB_CONNECTION", "requirement_control")
    try:
        connection = registry._document["connections"][connection_name]
    except KeyError as exc:
        raise _fail("sql_connection_missing") from exc
    for key, value in connection.items():
        if key.endswith("_env") and str(value).strip() and not os.getenv(str(value).strip()):
            raise _fail(f"environment_missing:{value}")
    try:
        registry.validate_named_connection(connection_name)
    except KeyError as exc:
        raise _fail("sql_connection_missing") from exc
    except (ValueError, RuntimeError) as exc:
        raise _fail(f"sql_connection_invalid:{exc}") from exc
    validate_signing_config()


def _validate_key(metadata: dict, values: dict[str, str]) -> None:
    if (metadata.get("key_id") != values["SRA_BOOTSTRAP_HANDOFF_KEY_ID"] or
            metadata.get("name") != KEY_NAME or metadata.get("status") != "active" or
            frozenset(metadata.get("scopes", ())) != KEY_SCOPES):
        raise _fail("handoff_key_mismatch")


def _build_values(port: int, state_dir: Path, key_id: str, raw: str) -> dict[str, str]:
    output_root = state_dir / "requirement_handoff_output"
    output_root.mkdir(mode=0o700, exist_ok=True)
    if output_root.is_symlink() or not output_root.is_dir() or not os.access(output_root, os.W_OK):
        raise _fail("output_root_invalid")
    values = {
        "SRA_BOOTSTRAP_STATE_VERSION": STATE_VERSION,
        "SRA_BOOTSTRAP_HANDOFF_KEY_ID": key_id,
        "REQUIREMENT_HANDOFF_API_BASE_URL": f"http://127.0.0.1:{port}",
        "REQUIREMENT_HANDOFF_ALLOW_INSECURE_LOCALHOST": "true",
        "REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL": KEY_NAME,
        "REQUIREMENT_HANDOFF_OUTPUT_ROOT": str(output_root.resolve()),
        "REQUIREMENT_HANDOFF_CREDENTIAL_ENV": "REQUIREMENT_HANDOFF_CREDENTIAL",
        "REQUIREMENT_HANDOFF_CREDENTIAL": raw,
    }
    RequirementHandoffConfig(
        api_base_url=values["REQUIREMENT_HANDOFF_API_BASE_URL"], logical_principal=KEY_NAME,
        credential_provider=lambda _: raw, output_root=output_root, allow_insecure_localhost=True,
    )
    return values


def _state_matches(path: Path, expected: dict[str, str] | None) -> bool:
    """Return true only when protected state can be proven to equal a version."""
    if expected is None:
        return not path.exists() and not path.is_symlink()
    try:
        return _read_state(path) == expected
    except (DeploymentBootstrapError, OSError):
        return False


def _rotate_handoff_key(
    *, store: ServiceKeyStore, state_file: Path, journal_file: Path,
    old_metadata: dict, old_values: dict[str, str] | None, port: int, state_dir: Path,
) -> dict[str, str]:
    """Rotate with a journal and conservative post-replace failure recovery."""
    metadata = None
    values = None
    journal_written = False
    try:
        metadata, raw = store.create(KEY_NAME, KEY_SCOPES, created_by="deployment-bootstrap-repair")
        values = _build_values(port, state_dir, metadata["key_id"], raw)
        _write_repair_journal(journal_file, old_metadata["key_id"], metadata["key_id"])
        journal_written = True
        try:
            _write_state(state_file, values)
        except Exception:
            # os.replace may have succeeded even when directory fsync reports an
            # error. Re-read rather than using call return as the commit boundary.
            if _state_matches(state_file, old_values):
                store.revoke(metadata["key_id"], revoked_by="deployment-bootstrap-repair-rollback")
                _remove_repair_journal(journal_file)
            # Replacement or indeterminate state retains both credentials and
            # the journal so a later explicit repair can prove their identities.
            raise
        store.revoke(old_metadata["key_id"], revoked_by="deployment-bootstrap-repair")
        _remove_repair_journal(journal_file)
        return values
    except Exception:
        # Creation succeeded but journaling definitely did not complete: state
        # has not been touched, so rolling back the replacement is safe.
        if metadata is not None and not journal_written:
            try:
                store.revoke(metadata["key_id"], revoked_by="deployment-bootstrap-repair-rollback")
            except Exception:
                pass
        raise


def bootstrap(*, project_root: Path, port: int, repair: bool = False) -> Path:
    bootstrap_env(project_root=project_root)
    _validate_site(project_root)
    state_dir = Path(os.getenv("SRA_DEPLOYMENT_STATE_DIR", str(project_root / ".sra_runtime")))
    if not state_dir.is_absolute():
        state_dir = project_root / state_dir
    _secure_directory(state_dir)
    state_file = state_dir / STATE_FILENAME
    journal_file = state_dir / REPAIR_JOURNAL_FILENAME
    store_path = Path(os.getenv("SRA_SERVICE_KEYS_FILE", str(project_root / ".sra_service_keys.json")))
    store = ServiceKeyStore(store_path)
    keys = [item for item in store.list_keys() if item.get("name") == KEY_NAME and item.get("status") == "active"]

    if repair:
        if journal_file.exists() or journal_file.is_symlink():
            journal = _read_repair_journal(journal_file)
            if not state_file.exists() or state_file.is_symlink():
                raise _fail("repair_state_ambiguous")
            current_values = _read_state(state_file)
            current_metadata = store.resolve(current_values["REQUIREMENT_HANDOFF_CREDENTIAL"])
            if current_metadata is None:
                raise _fail("repair_persisted_key_unresolved")
            _validate_key(current_metadata, current_values)
            active_ids = {item["key_id"] for item in keys}
            expected_ids = {journal["old_key_id"], journal["new_key_id"]}
            selected_id = current_metadata["key_id"]
            if selected_id == journal["new_key_id"]:
                if active_ids == expected_ids:
                    store.revoke(str(journal["old_key_id"]), revoked_by="deployment-bootstrap-repair-recovery")
                elif active_ids != {journal["new_key_id"]}:
                    raise _fail("repair_identity_ambiguous")
                _remove_repair_journal(journal_file)
                return state_file
            if selected_id == journal["old_key_id"]:
                if active_ids == expected_ids:
                    store.revoke(str(journal["new_key_id"]), revoked_by="deployment-bootstrap-repair-recovery")
                elif active_ids != {journal["old_key_id"]}:
                    raise _fail("repair_identity_ambiguous")
                _remove_repair_journal(journal_file)
                # The old state was proven intact. Cleanup completed the failed
                # attempt; this explicit command may now perform a fresh repair.
                return bootstrap(project_root=project_root, port=port, repair=True)
            raise _fail("repair_identity_ambiguous")

        if not state_file.exists() or state_file.is_symlink():
            # A first-run crash can leave one bootstrap-owned canonical key but
            # no retrievable raw credential. Explicit repair may replace only
            # that uniquely identified orphan; ordinary startup stays inert.
            if len(keys) != 1:
                raise _fail("repair_state_missing")
            orphan = keys[0]
            if (orphan.get("created_by") != "deployment-bootstrap" or
                    frozenset(orphan.get("scopes", ())) != KEY_SCOPES):
                raise _fail("repair_identity_ambiguous")
            _rotate_handoff_key(
                store=store, state_file=state_file, journal_file=journal_file,
                old_metadata=orphan, old_values=None, port=port, state_dir=state_dir,
            )
            return state_file
        old_values = _read_state(state_file)
        old_metadata = store.resolve(old_values["REQUIREMENT_HANDOFF_CREDENTIAL"])
        if old_metadata is None:
            raise _fail("repair_persisted_key_unresolved")
        _validate_key(old_metadata, old_values)

        others = [item for item in keys if item.get("key_id") != old_metadata["key_id"]]
        if others or len(keys) != 1 or keys[0].get("key_id") != old_metadata["key_id"]:
            raise _fail("repair_identity_ambiguous")
        values = _rotate_handoff_key(
            store=store, state_file=state_file, journal_file=journal_file,
            old_metadata=old_metadata, old_values=old_values, port=port, state_dir=state_dir,
        )
    elif state_file.exists() or state_file.is_symlink():
        values = _read_state(state_file)
        metadata = store.resolve(values["REQUIREMENT_HANDOFF_CREDENTIAL"])
        if metadata is None:
            raise _fail("handoff_credential_unresolved")
        _validate_key(metadata, values)
        if len(keys) != 1 or keys[0].get("key_id") != metadata.get("key_id"):
            raise _fail("canonical_key_ambiguous")
        expected = _build_values(port, state_dir, metadata["key_id"], values["REQUIREMENT_HANDOFF_CREDENTIAL"])
        if values != expected:
            raise _fail("generated_configuration_mismatch")
    else:
        if keys:
            raise _fail("canonical_key_without_state")
        metadata, raw = store.create(KEY_NAME, KEY_SCOPES, created_by="deployment-bootstrap")
        values = _build_values(port, state_dir, metadata["key_id"], raw)
        _write_state(state_file, values)

    metadata = store.resolve(values["REQUIREMENT_HANDOFF_CREDENTIAL"])
    if metadata is None:
        raise _fail("handoff_credential_unresolved")
    _validate_key(metadata, values)
    return state_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m config.deployment_bootstrap")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("bootstrap", "repair-handoff-credential"):
        command = subcommands.add_parser(name)
        command.add_argument("--project-root", type=Path, default=Path.cwd())
        command.add_argument("--port", type=int, default=int(os.getenv("PORT", "9002")))
    args = parser.parse_args(argv)
    try:
        # Keep stdout a single machine-readable non-secret record for Bash.
        with redirect_stdout(sys.stderr):
            state = bootstrap(
                project_root=args.project_root.resolve(), port=args.port,
                repair=args.command == "repair-handoff-credential",
            )
    except Exception as exc:
        reason = str(exc) if isinstance(exc, DeploymentBootstrapError) else "deployment_bootstrap_error:preflight_failed"
        print(reason, file=sys.stderr)
        return 1
    print(f"deployment_bootstrap_state_path={state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
