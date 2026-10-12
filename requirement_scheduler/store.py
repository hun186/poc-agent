from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4
from datetime import timedelta

from .migrations import (
    SCHEMA_VERSION, bootstrap_schema_statements,
    canonical_catalog_matches, canonical_v4_statements, classify_v1_catalog, migration_1_to_2_statements,
    migration_2_to_3_statements, migration_3_to_4_statements,
    read_catalog,
    validate_catalog_evidence, validate_schema_name, validation_queries,
)
from .models import MaterializedRun, RecurrenceSpec, RunPolicy, ScheduleAuditEvent, ScheduleVersionCreate, TriggerIdentity
from .lease import CONTROL_DOMAIN, LeaseProof, new_lease_token
from .recurrence import next_occurrence
from .recurrence import coalesce_latest
from .policy import Checkpoint, evaluate_selection
from .execution import (
    ExecutionFailure, ExecutionHandle, ExecutionManifest, ExecutionState, ExecutionStatus, FailureCategory,
    build_execution_manifest,
)
from .handoff import PreparedHandoff, checkpoint_outcome, prepared_handoff, verify_prepared


def _now() -> datetime: return datetime.now(timezone.utc).replace(microsecond=0)
def _id(prefix: str) -> str: return f"{prefix}_{uuid4().hex}"


def _sql_utc_now(cursor) -> datetime:
    """Read SQL Server's authoritative clock as an aware UTC datetimeoffset."""
    cursor.execute("SELECT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')")
    row = cursor.fetchone()
    value = row[0] if row and len(row) == 1 else None
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() != timedelta(0)):
        raise RuntimeError("persistence_error")
    return value.astimezone(timezone.utc)


def _safe_error(exc: Exception) -> Exception:
    if isinstance(exc, (KeyError, ValueError)) and str(exc).strip("'") in {
        "schedule_not_found", "schedule_version_not_found", "schedule_enabled",
        "schedule_version_not_approved", "schedule_name_invalid", "recurrence_invalid",
        "timezone_naive", "timezone_invalid", "recurrence_second_precision_required",
        "schedule_model_invalid", "requirement_set_not_found",
        "requirement_idempotency_conflict", "requirement_product_request_invalid",
        "requirement_product_request_terminal", "requirement_product_task_invalid",
        "requirement_product_task_conflict", "requirement_product_create_incomplete",
        "requirement_product_no_selectable_first_run",
        "requirement_task_not_found", "requirement_task_provisioning",
        "requirement_task_conflict", "requirement_task_state_invalid",
        "requirement_task_update_incomplete", "requirement_task_version_invalid",
        "requirement_product_owned_schedule",
        "requirement_product_input_incomplete",
    }: return exc
    return RuntimeError("persistence_error")


def _is_scheduled_occurrence_conflict(exc: Exception) -> bool:
    text = " ".join(str(part) for part in getattr(exc, "args", (exc,)))
    return ("23000" in text and ("2601" in text or "2627" in text)
            and "UX_schedule_run_scheduled" in text)


def _is_unique_key_conflict(exc: Exception) -> bool:
    """Recognize only SQL Server duplicate-key errors, never arbitrary DB failures."""
    text = " ".join(str(part) for part in getattr(exc, "args", (exc,)))
    return "23000" in text and ("2601" in text or "2627" in text)


class ScheduleStore:
    """SQL Server Phase 1C authority. No method writes Phase 1B tables."""
    def __init__(self, registry, connection_ref: str, schema: str = "sra_schedule", requirement_schema: str = "sra_requirement", *, audit_sink=None, audit_drain_limit: int = 20):
        self.registry = registry; self.connection_ref = connection_ref
        self.schema = validate_schema_name(schema); self.requirement_schema = validate_schema_name(requirement_schema)
        self.audit_sink = audit_sink
        self.audit_drain_limit = max(1, min(int(audit_drain_limit), 100))

    @property
    def t(self): return f"[{self.schema}]"

    def _connect(self):
        try: return self.registry.open_named_connection(self.connection_ref)
        except Exception as exc: raise RuntimeError("persistence_error") from exc

    @staticmethod
    def _audit_event(action: str, actor: str, schedule_id: str, *,
                     schedule_version_id: str | None = None, payload: dict[str, Any] | None = None,
                     created_at: datetime | None = None) -> ScheduleAuditEvent:
        allowed = {
            "requirement_schedule.created", "requirement_schedule.updated",
            "requirement_schedule.version_created", "requirement_schedule.version_approved",
            "requirement_schedule.version_retired", "requirement.task.updated",
            "requirement_schedule.enabled", "requirement_schedule.disabled",
            "requirement_handoff.prepared", "requirement_handoff.dispatched",
            "requirement_handoff.reconciled", "requirement_handoff.remote_authorization_failed",
            "requirement_handoff.artifact_reconciled", "requirement_handoff.item_completed",
            "requirement_handoff.item_failed", "requirement_handoff.item_recovery_required",
        }
        if action not in allowed or not actor or len(actor) > 128:
            raise ValueError("audit_event_invalid")
        if not schedule_id:
            raise ValueError("audit_event_invalid")
        payload_keys = {
            "requirement_schedule.created": {"requirement_set_id"},
            "requirement_schedule.updated": {"field"},
            "requirement_schedule.version_created": {"version_number"},
            "requirement_schedule.version_approved": {"version_number"},
            "requirement_schedule.version_retired": {"version_number"},
            "requirement.task.updated": {"task_id", "revision", "operation"},
            "requirement_schedule.enabled": set(),
            "requirement_schedule.disabled": set(),
            "requirement_handoff.prepared": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "output_root_fingerprint", "fencing_generation"},
            "requirement_handoff.dispatched": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "fencing_generation", "neutral_state"},
            "requirement_handoff.reconciled": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "fencing_generation", "neutral_state", "category"},
            "requirement_handoff.remote_authorization_failed": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "fencing_generation", "category"},
            "requirement_handoff.artifact_reconciled": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "output_root_fingerprint", "fencing_generation", "artifact_sha256", "artifact_relative_path"},
            "requirement_handoff.item_completed": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "fencing_generation", "neutral_state", "artifact_sha256", "artifact_relative_path"},
            "requirement_handoff.item_failed": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "fencing_generation", "neutral_state", "category"},
            "requirement_handoff.item_recovery_required": {"batch_run_id", "run_item_id", "submission_id", "workflow_id", "fencing_generation", "neutral_state", "category"},
        }
        body = payload or {}
        if not isinstance(body, dict) or not set(body).issubset(payload_keys[action]):
            raise ValueError("audit_payload_invalid")
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(encoded) > 2000:
            raise ValueError("audit_payload_invalid")
        return ScheduleAuditEvent(_id("aud"), action, actor, schedule_id, schedule_version_id,
                                  body, created_at or _now())

    def _enqueue_audit_event(self, cursor, event: ScheduleAuditEvent) -> None:
        payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        cursor.execute(
            f"INSERT INTO {self.t}.[requirement_schedule_audit_outbox](audit_event_id,action,actor,schedule_id,schedule_version_id,batch_run_id,safe_payload_json,created_at,delivery_attempt_count) VALUES (?,?,?,?,?,?,?,?,0)",
            event.audit_event_id, event.action, event.actor, event.schedule_id,
            event.schedule_version_id, event.payload.get("batch_run_id"), payload, event.created_at,
        )

    def _drain_best_effort(self) -> None:
        if self.audit_sink is None:
            return
        try:
            from .audit_delivery import drain_audit_outbox
            drain_audit_outbox(self, self.audit_sink, limit=self.audit_drain_limit, now_utc=_now())
        except Exception:
            # The committed SQL outbox is authoritative; projection is retried later.
            return

    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def acquire_lease(self, owner_id: str, lease_duration: float) -> LeaseProof:
        if not owner_id or len(owner_id) > 128 or lease_duration <= 0: raise ValueError("lease_invalid")
        connection=self._connect()
        try:
            c=connection.cursor(); now=_sql_utc_now(c)
            c.execute(f"SELECT owner_id,lease_token,fencing_generation,expires_at FROM {self.t}.[requirement_handoff_coordinator_leases] WITH (UPDLOCK,HOLDLOCK) WHERE control_domain=?",CONTROL_DOMAIN)
            row=c.fetchone(); token=new_lease_token()
            if row is None:
                generation=1; expires=now+timedelta(seconds=lease_duration)
                c.execute(f"INSERT INTO {self.t}.[requirement_handoff_coordinator_leases](control_domain,owner_id,lease_token,fencing_generation,heartbeat_at,expires_at,updated_at) VALUES (?,?,?,?,?,?,?)",CONTROL_DOMAIN,owner_id,token,generation,now,expires,now)
            elif row[3] <= now:
                if int(row[2]) >= 2**63-1: raise RuntimeError("lease_generation_exhausted")
                generation=int(row[2])+1; expires=now+timedelta(seconds=lease_duration)
                c.execute(f"UPDATE {self.t}.[requirement_handoff_coordinator_leases] SET owner_id=?,lease_token=?,fencing_generation=?,heartbeat_at=?,expires_at=?,updated_at=? WHERE control_domain=? AND fencing_generation=? AND expires_at<=?",owner_id,token,generation,now,expires,now,CONTROL_DOMAIN,row[2],now)
                if getattr(c,"rowcount",0)!=1: raise RuntimeError("lease_unavailable")
            else: raise RuntimeError("lease_unavailable")
            connection.commit(); return LeaseProof(CONTROL_DOMAIN,owner_id,token,generation,expires)
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def renew_lease(self, lease: LeaseProof, lease_duration: float) -> LeaseProof:
        connection=self._connect()
        try:
            c=connection.cursor(); now=_sql_utc_now(c); expires=now+timedelta(seconds=lease_duration)
            c.execute(f"UPDATE {self.t}.[requirement_handoff_coordinator_leases] SET heartbeat_at=?,expires_at=?,updated_at=? WHERE control_domain=? AND owner_id=? AND lease_token=? AND fencing_generation=? AND expires_at>?",now,expires,now,lease.control_domain,lease.owner_id,lease.lease_token,lease.fencing_generation,now)
            if getattr(c,"rowcount",0)!=1: raise RuntimeError("lease_lost")
            connection.commit(); return LeaseProof(lease.control_domain,lease.owner_id,lease.lease_token,lease.fencing_generation,expires)
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def release_lease(self, lease: LeaseProof) -> bool:
        connection=self._connect()
        try:
            c=connection.cursor(); now=_sql_utc_now(c)
            c.execute(f"UPDATE {self.t}.[requirement_handoff_coordinator_leases] SET expires_at=?,updated_at=? WHERE control_domain=? AND owner_id=? AND lease_token=? AND fencing_generation=? AND expires_at>?",now,now,lease.control_domain,lease.owner_id,lease.lease_token,lease.fencing_generation,now)
            changed=getattr(c,"rowcount",0)==1; connection.commit(); return changed
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def initialize(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT OBJECT_ID(?,N'U')", f"{self.schema}.schema_version")
            object_row = cursor.fetchone()
            marker_preexisted = object_row is not None and object_row[0] is not None
            # pyodbc returns one row whose value is NULL when the object is absent.
            # Scripted DB-API fakes may return no row; both spell a proven bootstrap.
            if not marker_preexisted:
                for sql in bootstrap_schema_statements(self.schema): cursor.execute(sql)
            cursor.execute(f"SELECT version FROM {self.t}.[schema_version] WITH (UPDLOCK,HOLDLOCK)")
            marker_rows = tuple(cursor.fetchall())
            if len(marker_rows) > 1 or (not marker_rows and marker_preexisted):
                raise RuntimeError("unsupported_requirement_schedule_schema")
            if marker_rows:
                if len(marker_rows[0]) != 1:
                    raise RuntimeError("unsupported_requirement_schedule_schema")
                try:
                    version = int(marker_rows[0][0])
                except (TypeError, ValueError, OverflowError) as exc:
                    raise RuntimeError("unsupported_requirement_schedule_schema") from exc
            else:
                version = 0
            if version == 0:
                for sql in canonical_v4_statements(self.schema, self.requirement_schema): cursor.execute(sql)
            elif version == 1:
                shape = classify_v1_catalog(cursor, self.schema, self.requirement_schema)
                self._validate_legacy_configurations(cursor)
                if shape == "pr200_v1":
                    repair = self._pr200_identity_repair_statements()
                    for sql in repair[:-2]:
                        cursor.execute(sql)
                    migration = migration_1_to_2_statements(self.schema, shape)
                    cursor.execute(migration[0])  # widen before copying external identities
                    for sql in repair[-2:]:
                        cursor.execute(sql)
                    migration = migration[1:]
                else:
                    migration = migration_1_to_2_statements(self.schema, shape)
                for sql in migration:
                    cursor.execute(sql)
                for sql in migration_2_to_3_statements(self.schema):
                    cursor.execute(sql)
                for sql in migration_3_to_4_statements(self.schema, self.requirement_schema):
                    cursor.execute(sql)
            elif version == 2:
                # v2 was fully catalog-validated by the previous release. Migration
                # remains one transaction; v3 and v4 DDL commit only after full v4 validation.
                for sql in migration_2_to_3_statements(self.schema): cursor.execute(sql)
                for sql in migration_3_to_4_statements(self.schema, self.requirement_schema): cursor.execute(sql)
            elif version == 3:
                # v3 was fully catalog-validated by the previous release. Product v4
                # adds only the reviewed control-plane tables and their constraints/indexes.
                for sql in migration_3_to_4_statements(self.schema, self.requirement_schema): cursor.execute(sql)
            elif version != SCHEMA_VERSION: raise RuntimeError("unsupported_requirement_schedule_schema")
            for name, sql, params, expected in validation_queries(self.schema, self.requirement_schema):
                cursor.execute(sql, *params); rows = tuple(cursor.fetchall())
                valid = validate_catalog_evidence(self.schema, expected, rows)
                if not valid: raise RuntimeError("unsupported_requirement_schedule_schema")
            if not canonical_catalog_matches(
                read_catalog(cursor, self.schema), self.schema, self.requirement_schema
            ):
                raise RuntimeError("unsupported_requirement_schedule_schema")
            if version == 0:
                cursor.execute(f"INSERT INTO {self.t}.[schema_version](version) VALUES (?)", SCHEMA_VERSION)
            elif version in {1, 2, 3}:
                cursor.execute(f"UPDATE {self.t}.[schema_version] SET version=? WHERE version=?", SCHEMA_VERSION, version)
                if getattr(cursor, "rowcount", 1) != 1:
                    raise RuntimeError("unsupported_requirement_schedule_schema")
            cursor.execute(f"SELECT version FROM {self.t}.[schema_version] WITH (UPDLOCK,HOLDLOCK)")
            final_markers = tuple(cursor.fetchall())
            try:
                final_marker_valid = (
                    len(final_markers) == 1
                    and len(final_markers[0]) == 1
                    and int(final_markers[0][0]) == SCHEMA_VERSION
                )
            except (TypeError, ValueError, OverflowError):
                final_marker_valid = False
            if not final_marker_valid:
                raise RuntimeError("unsupported_requirement_schedule_schema")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            if str(exc) == "unsupported_requirement_schedule_schema": raise
            raise _safe_error(exc) from exc
        finally: connection.close()
        self._drain_best_effort()

    def _validate_legacy_configurations(self, cursor) -> None:
        cursor.execute(
            f"SELECT v.timezone,v.recurrence_json,v.run_policy,v.model,v.config_sha256,v.status,"
            f"s.enabled,s.active_version_id,v.schedule_version_id,v.approved_by,v.approved_at "
            f"FROM {self.t}.[requirement_schedule_versions] v LEFT JOIN {self.t}.[requirement_schedules] s "
            f"ON s.schedule_id=v.schedule_id"
        )
        for row in cursor.fetchall():
            timezone_name, recurrence_json, policy, model, digest, status, enabled, active_id, vid, approved_by, approved_at = row
            must_validate = status == "approved" or (bool(enabled) and active_id == vid)
            if status == "approved" and (approved_by is None or approved_at is None):
                raise RuntimeError("unsupported_requirement_schedule_schema")
            if must_validate:
                try:
                    self._validate_persisted_config(timezone_name, recurrence_json, policy, model, digest)
                except ValueError as exc:
                    raise RuntimeError("unsupported_requirement_schedule_schema") from exc

    def _pr200_identity_repair_statements(self) -> tuple[str, ...]:
        s, r = self.t, f"[{self.requirement_schema}]"
        # All assertions execute before the first UPDATE, so unexpected history
        # cannot be partly rewritten even before transaction rollback.
        return (
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_runs] WHERE phase1a_source_sha256 IS NOT NULL OR phase1a_output_root_fingerprint IS NOT NULL OR handoff_started_at IS NOT NULL OR handed_off_at IS NOT NULL OR reconciled_at IS NOT NULL OR completed_at IS NOT NULL OR deadline_elapsed_during_execution<>0 OR success_count<>0 OR failure_count<>0 OR state NOT IN ('handoff_pending','blocked_no_snapshot')) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_run_items] WHERE remote_job_id IS NOT NULL OR remote_job_state IS NOT NULL OR artifact_relative_path IS NOT NULL OR handoff_started_at IS NOT NULL OR dispatched_at IS NOT NULL OR remote_completed_at IS NOT NULL OR artifact_reconciled_at IS NOT NULL OR completed_at IS NOT NULL OR expired_before_handoff<>0 OR deadline_elapsed_during_execution<>0 OR execution_state NOT IN ('handoff_pending','not_selected')) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_schedule_item_state] WHERE last_successful_requirement_version_id IS NOT NULL OR last_successful_requirement_version_number IS NOT NULL OR last_successful_run_item_id IS NOT NULL OR last_successful_at IS NOT NULL) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_runs] WHERE phase1a_batch_id<>N'phase1c-'+batch_run_id) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_run_items] WHERE (selection_status='selected' AND phase1a_task_id<>requirement_id) OR (selection_status='skipped' AND phase1a_task_id IS NOT NULL) OR selection_status NOT IN ('selected','skipped')) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_run_items] i LEFT JOIN {r}.[requirement_versions] v ON v.requirement_version_id=i.requirement_version_id AND v.requirement_id=i.requirement_id AND v.version_number=i.requirement_version_number LEFT JOIN {r}.[requirements] q ON q.requirement_id=i.requirement_id WHERE i.selection_status='selected' AND (v.requirement_version_id IS NULL OR q.requirement_id IS NULL OR q.external_item_id IS NULL OR LEN(q.external_item_id)>240 OR (SELECT COUNT(*) FROM {r}.[requirements] q2 WHERE q2.external_item_id=q.external_item_id)<>1)) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"UPDATE {s}.[requirement_batch_runs] SET phase1a_batch_id=N'reqrun-'+batch_run_id WHERE phase1a_batch_id=N'phase1c-'+batch_run_id",
            f"UPDATE i SET phase1a_task_id=q.external_item_id FROM {s}.[requirement_batch_run_items] i JOIN {r}.[requirements] q ON q.requirement_id=i.requirement_id WHERE i.selection_status='selected' AND i.phase1a_task_id=i.requirement_id",
        )

    def create_schedule(self, *, name: str, requirement_set_id: str, actor: str, schedule_id: str | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 240:
            raise ValueError("schedule_name_invalid")
        sid, now = schedule_id or _id("sch"), _now()
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT requirement_set_id FROM [{self.requirement_schema}].[requirement_sets] WHERE requirement_set_id=?",
                requirement_set_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("requirement_set_not_found")
            if schedule_id is not None:
                c.execute(
                    f"SELECT name,requirement_set_id,enabled,active_version_id,next_run_at,created_by,created_at,updated_by,updated_at "
                    f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                    sid,
                )
                existing = c.fetchone()
                if existing is not None:
                    if existing[0] != clean_name or existing[1] != requirement_set_id:
                        raise RuntimeError("persistence_error")
                    connection.commit()
                    return {
                        "schedule_id": sid,
                        "name": existing[0],
                        "requirement_set_id": existing[1],
                        "enabled": bool(existing[2]),
                        "active_version_id": existing[3],
                        "next_run_at": existing[4],
                        "created_by": existing[5],
                        "created_at": existing[6],
                        "updated_by": existing[7],
                        "updated_at": existing[8],
                    }
            c.execute(
                f"INSERT INTO {self.t}.[requirement_schedules](schedule_id,name,requirement_set_id,enabled,active_version_id,next_run_at,created_by,created_at,updated_by,updated_at) VALUES (?,?,?,0,NULL,NULL,?,?,?,?)",
                sid, clean_name, requirement_set_id, actor, now, actor, now,
            )
            self._enqueue_audit_event(
                c,
                self._audit_event(
                    "requirement_schedule.created",
                    actor,
                    sid,
                    payload={"requirement_set_id": requirement_set_id},
                    created_at=now,
                ),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()
        self._drain_best_effort()
        return {
            "schedule_id": sid,
            "name": clean_name,
            "requirement_set_id": requirement_set_id,
            "enabled": False,
            "active_version_id": None,
            "next_run_at": None,
            "created_by": actor,
            "created_at": now,
            "updated_by": actor,
            "updated_at": now,
        }

    @staticmethod
    def _product_request_dict(row) -> dict[str, Any]:
        keys = (
            "request_id", "principal_kind", "principal_id", "operation",
            "idempotency_key", "request_sha256", "state", "task_id", "source_id",
            "import_run_id", "snapshot_id", "schedule_id", "schedule_version_id",
            "batch_run_id", "base_task_revision", "result_task_revision",
            "base_snapshot_id", "safe_result_json", "error_code",
            "created_at", "updated_at", "completed_at",
        )
        result = dict(zip(keys, row, strict=True))
        if result["safe_result_json"] is not None:
            try:
                result["safe_result"] = json.loads(result["safe_result_json"])
            except (TypeError, json.JSONDecodeError):
                raise RuntimeError("persistence_error") from None
        else:
            result["safe_result"] = None
        return result

    def reserve_product_task_create(
        self,
        *,
        principal_kind: str,
        principal_id: str,
        idempotency_key: str,
        request_sha256: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        if (
            principal_kind != "user"
            or not principal_id
            or len(principal_id) > 128
            or not idempotency_key
            or len(idempotency_key) > 128
            or len(request_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in request_sha256)
        ):
            raise ValueError("requirement_product_request_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE principal_kind=? AND principal_id=? AND operation='task_create' AND idempotency_key=?",
                principal_kind, principal_id, idempotency_key,
            )
            existing = c.fetchone()
            if existing is not None:
                result = self._product_request_dict(existing)
                if result["request_sha256"] != request_sha256:
                    raise ValueError("requirement_idempotency_conflict")
                connection.commit()
                return result

            request_id = _id("preq")
            task_id = _id("task")
            source_id = _id("src")
            import_run_id = _id("run")
            snapshot_id = _id("snap")
            schedule_id = _id("sch")
            schedule_version_id = _id("sv")
            c.execute(
                f"INSERT INTO {self.t}.[requirement_product_requests]("
                "request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,"
                "task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,"
                "batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,"
                "created_at,updated_at,completed_at"
                ") VALUES (?,?,?,?,?,?,'reserved',?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,?,?,NULL)",
                request_id, principal_kind, principal_id, "task_create", idempotency_key,
                request_sha256, task_id, source_id, import_run_id, snapshot_id,
                schedule_id, schedule_version_id, now_utc, now_utc,
            )
            connection.commit()
            return {
                "request_id": request_id,
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "operation": "task_create",
                "idempotency_key": idempotency_key,
                "request_sha256": request_sha256,
                "state": "reserved",
                "task_id": task_id,
                "source_id": source_id,
                "import_run_id": import_run_id,
                "snapshot_id": snapshot_id,
                "schedule_id": schedule_id,
                "schedule_version_id": schedule_version_id,
                "batch_run_id": None,
                "base_task_revision": None,
                "result_task_revision": None,
                "base_snapshot_id": None,
                "safe_result_json": None,
                "safe_result": None,
                "error_code": None,
                "created_at": now_utc,
                "updated_at": now_utc,
                "completed_at": None,
            }
        except Exception as exc:
            connection.rollback()
            if _is_unique_key_conflict(exc):
                read_connection = self._connect()
                try:
                    cursor = read_connection.cursor()
                    cursor.execute(
                        f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                        f"FROM {self.t}.[requirement_product_requests] "
                        f"WHERE principal_kind=? AND principal_id=? AND operation='task_create' AND idempotency_key=?",
                        principal_kind, principal_id, idempotency_key,
                    )
                    raced = cursor.fetchone()
                    if raced is None:
                        raise RuntimeError("persistence_error")
                    result = self._product_request_dict(raced)
                    if result["request_sha256"] != request_sha256:
                        raise ValueError("requirement_idempotency_conflict")
                    return result
                except Exception as read_exc:
                    raise _safe_error(read_exc) from read_exc
                finally:
                    read_connection.close()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def mark_product_request_in_progress(self, request_id: str, *, now_utc: datetime) -> None:
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='in_progress',updated_at=? "
                f"WHERE request_id=? AND operation='task_create' AND state IN ('reserved','failed_recoverable')",
                now_utc, request_id,
            )
            c.execute(
                f"SELECT state FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) WHERE request_id=?",
                request_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("requirement_product_request_invalid")
            if row[0] not in {"in_progress", "succeeded"}:
                raise ValueError("requirement_product_request_terminal")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def fail_product_request_terminal(
        self, request_id: str, *, error_code: str, now_utc: datetime
    ) -> None:
        if not error_code or len(error_code) > 64:
            raise ValueError("requirement_product_request_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='failed_terminal',error_code=?,safe_result_json=NULL,updated_at=?,completed_at=? "
                f"WHERE request_id=? AND state<>'succeeded'",
                error_code, now_utc, now_utc, request_id,
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def create_product_task_provisioning(
        self,
        *,
        task_id: str,
        schedule_id: str,
        source_id: str,
        execution_kind: str,
        actor: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        if execution_kind not in {"once", "recurring"}:
            raise ValueError("requirement_product_task_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision,created_by,created_at,updated_by,updated_at "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            existing = c.fetchone()
            if existing is not None:
                if (
                    existing[1] != schedule_id
                    or existing[2] != source_id
                    or existing[3] != execution_kind
                ):
                    raise ValueError("requirement_product_task_conflict")
                connection.commit()
                keys = ("task_id","schedule_id","source_id","execution_kind","product_state","revision","created_by","created_at","updated_by","updated_at")
                return dict(zip(keys, existing, strict=True))
            c.execute(
                f"INSERT INTO {self.t}.[requirement_product_tasks]("
                "task_id,schedule_id,source_id,execution_kind,product_state,revision,"
                "created_by,created_at,updated_by,updated_at"
                ") VALUES (?,?,?,?,'provisioning',1,?,?,?,?)",
                task_id, schedule_id, source_id, execution_kind,
                actor, now_utc, actor, now_utc,
            )
            connection.commit()
            return {
                "task_id": task_id,
                "schedule_id": schedule_id,
                "source_id": source_id,
                "execution_kind": execution_kind,
                "product_state": "provisioning",
                "revision": 1,
                "created_by": actor,
                "created_at": now_utc,
                "updated_by": actor,
                "updated_at": now_utc,
            }
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def list_product_tasks(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Read only finalized Product Tasks; never expose provisioning identities."""
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        return self._query(
            f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision,"
            f"created_by,created_at,updated_by,updated_at "
            f"FROM {self.t}.[requirement_product_tasks] "
            f"WHERE product_state IN ('active','disabled') "
            f"ORDER BY created_at DESC,task_id "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            offset, limit,
        )

    def list_product_run_bindings(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List eligible Run->Task bindings without exposing unowned or provisioning runs."""
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        return self._query(
            f"SELECT r.batch_run_id,t.task_id "
            f"FROM {self.t}.[requirement_batch_runs] r "
            f"JOIN {self.t}.[requirement_product_tasks] t ON t.schedule_id=r.schedule_id "
            f"WHERE t.product_state IN ('active','disabled') "
            f"ORDER BY r.created_at DESC,r.batch_run_id "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            offset, limit,
        )

    def get_product_task_for_run(self, batch_run_id: str) -> dict[str, Any]:
        """Resolve the owning finalized Product Task; hide provisioning and low-level Runs."""
        rows = self._query(
            f"SELECT t.task_id,t.schedule_id,t.source_id,t.execution_kind,"
            f"t.product_state,t.revision,t.created_by,t.created_at,t.updated_by,t.updated_at "
            f"FROM {self.t}.[requirement_batch_runs] r "
            f"JOIN {self.t}.[requirement_product_tasks] t ON t.schedule_id=r.schedule_id "
            f"WHERE r.batch_run_id=? AND t.product_state IN ('active','disabled')",
            batch_run_id,
        )
        if not rows:
            raise KeyError("requirement_run_unavailable")
        return rows[0]

    def get_product_task(self, task_id: str, *, include_provisioning: bool = False) -> dict[str, Any]:
        clause = "" if include_provisioning else " AND product_state IN ('active','disabled')"
        rows = self._query(
            f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision,created_by,created_at,updated_by,updated_at "
            f"FROM {self.t}.[requirement_product_tasks] WHERE task_id=?{clause}",
            task_id,
        )
        if not rows:
            raise KeyError("requirement_task_not_found")
        return rows[0]

    def reserve_product_task_update(
        self,
        *,
        task_id: str,
        principal_kind: str,
        principal_id: str,
        idempotency_key: str,
        request_sha256: str,
        allocate_schedule_version: bool,
        now_utc: datetime,
    ) -> dict[str, Any]:
        if (
            not task_id
            or principal_kind != "user"
            or not principal_id
            or len(principal_id) > 128
            or not idempotency_key
            or len(idempotency_key) > 128
            or len(request_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in request_sha256)
        ):
            raise ValueError("requirement_product_request_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE principal_kind=? AND principal_id=? AND operation='task_update' AND idempotency_key=?",
                principal_kind,
                principal_id,
                idempotency_key,
            )
            existing = c.fetchone()
            if existing is not None:
                result = self._product_request_dict(existing)
                if result["request_sha256"] != request_sha256:
                    raise ValueError("requirement_idempotency_conflict")
                connection.commit()
                return result

            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise KeyError("requirement_task_not_found")
            if task[4] == "provisioning":
                raise ValueError("requirement_task_provisioning")
            if task[4] not in {"active", "disabled"}:
                raise ValueError("requirement_product_task_conflict")

            request_id = _id("preq")
            schedule_version_id = _id("sv") if allocate_schedule_version else None
            base_revision = int(task[5])
            c.execute(
                f"INSERT INTO {self.t}.[requirement_product_requests]("
                "request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,"
                "task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,"
                "batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,"
                "created_at,updated_at,completed_at"
                ") VALUES (?,?,?,?,?,?,'reserved',?,?,NULL,NULL,?,?,NULL,?,NULL,NULL,NULL,NULL,?,?,NULL)",
                request_id,
                principal_kind,
                principal_id,
                "task_update",
                idempotency_key,
                request_sha256,
                task_id,
                task[2],
                task[1],
                schedule_version_id,
                base_revision,
                now_utc,
                now_utc,
            )
            connection.commit()
            return {
                "request_id": request_id,
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "operation": "task_update",
                "idempotency_key": idempotency_key,
                "request_sha256": request_sha256,
                "state": "reserved",
                "task_id": task_id,
                "source_id": task[2],
                "import_run_id": None,
                "snapshot_id": None,
                "schedule_id": task[1],
                "schedule_version_id": schedule_version_id,
                "batch_run_id": None,
                "base_task_revision": base_revision,
                "result_task_revision": None,
                "base_snapshot_id": None,
                "safe_result_json": None,
                "safe_result": None,
                "error_code": None,
                "created_at": now_utc,
                "updated_at": now_utc,
                "completed_at": None,
            }
        except Exception as exc:
            connection.rollback()
            if _is_unique_key_conflict(exc):
                read_connection = self._connect()
                try:
                    cursor = read_connection.cursor()
                    cursor.execute(
                        f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                        f"FROM {self.t}.[requirement_product_requests] "
                        f"WHERE principal_kind=? AND principal_id=? AND operation='task_update' AND idempotency_key=?",
                        principal_kind,
                        principal_id,
                        idempotency_key,
                    )
                    raced = cursor.fetchone()
                    if raced is None:
                        raise RuntimeError("persistence_error")
                    result = self._product_request_dict(raced)
                    if result["request_sha256"] != request_sha256:
                        raise ValueError("requirement_idempotency_conflict")
                    return result
                except Exception as read_exc:
                    raise _safe_error(read_exc) from read_exc
                finally:
                    read_connection.close()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def mark_product_task_update_in_progress(
        self, request_id: str, *, now_utc: datetime
    ) -> None:
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='in_progress',updated_at=? "
                f"WHERE request_id=? AND operation='task_update' "
                f"AND state IN ('reserved','failed_recoverable')",
                now_utc,
                request_id,
            )
            c.execute(
                f"SELECT state FROM {self.t}.[requirement_product_requests] "
                f"WITH (UPDLOCK,HOLDLOCK) WHERE request_id=? AND operation='task_update'",
                request_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("requirement_product_request_invalid")
            if row[0] not in {"in_progress", "succeeded"}:
                raise ValueError("requirement_product_request_terminal")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def finalize_product_task_update(
        self,
        *,
        request_id: str,
        task_id: str,
        actor: str,
        name: str | None,
        enabled: bool | None,
        is_superuser: bool,
        now_utc: datetime,
    ) -> dict[str, Any]:
        if name is not None:
            name = name.strip()
            if not name or len(name) > 240:
                raise ValueError("schedule_name_invalid")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("requirement_task_state_invalid")
        if enabled is not None and not is_superuser:
            raise PermissionError("superuser_required")
        if name is None and enabled is None:
            raise ValueError("requirement_task_state_invalid")

        connection = self._connect()
        should_drain = False
        terminal_error: str | None = None
        outcome: dict[str, Any] | None = None
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) WHERE request_id=?",
                request_id,
            )
            request_row = c.fetchone()
            if request_row is None:
                raise KeyError("requirement_product_request_invalid")
            request = self._product_request_dict(request_row)
            if request["operation"] != "task_update" or request["task_id"] != task_id:
                raise ValueError("requirement_product_request_invalid")
            if request["state"] == "succeeded":
                result = request["safe_result"]
                if not isinstance(result, dict):
                    raise RuntimeError("persistence_error")
                connection.commit()
                return result
            if request["state"] == "failed_terminal":
                raise ValueError(
                    request["error_code"] or "requirement_product_request_terminal"
                )
            if request["state"] not in {"reserved", "in_progress", "failed_recoverable"}:
                raise ValueError("requirement_product_request_invalid")

            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise KeyError("requirement_task_not_found")
            if task[4] == "provisioning":
                raise ValueError("requirement_task_provisioning")
            if int(task[5]) != int(request["base_task_revision"]):
                terminal_error = "requirement_task_conflict"
            elif enabled is not None and task[3] != "recurring":
                terminal_error = "requirement_task_state_invalid"

            if terminal_error is not None:
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='failed_terminal',safe_result_json=NULL,error_code=?,"
                    f"updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    terminal_error,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
            else:
                c.execute(
                    f"SELECT name,enabled,active_version_id,next_run_at "
                    f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                    task[1],
                )
                schedule = c.fetchone()
                if schedule is None or task[1] != request["schedule_id"]:
                    raise ValueError("requirement_product_task_conflict")

                current_enabled = bool(schedule[1])
                current_state = str(task[4])
                if task[3] == "recurring" and (
                    (current_state == "active") != current_enabled
                ):
                    raise RuntimeError("persistence_error")

                target_enabled = current_enabled if enabled is None else bool(enabled)
                target_state = current_state
                target_due = schedule[3]
                if enabled is not None:
                    target_state = "active" if target_enabled else "disabled"
                    if target_enabled == current_enabled:
                        target_due = schedule[3]
                    elif target_enabled:
                        if not schedule[2]:
                            raise ValueError("schedule_version_not_approved")
                        c.execute(
                            f"SELECT status,timezone,recurrence_json,run_policy,model,config_sha256 "
                            f"FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
                            f"WHERE schedule_version_id=?",
                            schedule[2],
                        )
                        version = c.fetchone()
                        if version is None or version[0] != "approved":
                            raise ValueError("schedule_version_not_approved")
                        config = self._validate_persisted_config(
                            version[1], version[2], version[3], version[4], version[5]
                        )
                        target_due = next_occurrence(
                            config.recurrence, config.timezone, now_utc
                        )
                    else:
                        target_due = None

                target_name = schedule[0] if name is None else name
                if name is not None:
                    c.execute(
                        f"UPDATE {self.t}.[requirement_schedules] "
                        f"SET name=?,updated_by=?,updated_at=? WHERE schedule_id=?",
                        target_name,
                        actor,
                        now_utc,
                        task[1],
                    )
                    self._enqueue_audit_event(
                        c,
                        self._audit_event(
                            "requirement_schedule.updated",
                            actor,
                            task[1],
                            payload={"field": "name"},
                            created_at=now_utc,
                        ),
                    )

                if enabled is not None:
                    c.execute(
                        f"UPDATE {self.t}.[requirement_schedules] "
                        f"SET enabled=?,next_run_at=?,updated_by=?,updated_at=? "
                        f"WHERE schedule_id=?",
                        target_enabled,
                        target_due,
                        actor,
                        now_utc,
                        task[1],
                    )
                    if target_enabled != current_enabled:
                        self._enqueue_audit_event(
                            c,
                            self._audit_event(
                                "requirement_schedule.enabled"
                                if target_enabled
                                else "requirement_schedule.disabled",
                                actor,
                                task[1],
                                created_at=now_utc,
                            ),
                        )

                new_revision = int(task[5]) + 1
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_tasks] "
                    f"SET product_state=?,revision=?,updated_by=?,updated_at=? "
                    f"WHERE task_id=? AND revision=?",
                    target_state,
                    new_revision,
                    actor,
                    now_utc,
                    task_id,
                    request["base_task_revision"],
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_task_conflict")

                result = {
                    "mode": "in_place",
                    "task_id": task_id,
                    "task_revision": new_revision,
                    "name": target_name,
                    "execution_kind": task[3],
                    "product_state": target_state,
                    "schedule_id": task[1],
                    "enabled": target_enabled,
                    "active_version_id": schedule[2],
                    "next_run_at": (
                        target_due.isoformat()
                        if isinstance(target_due, datetime)
                        else target_due
                    ),
                }
                encoded = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if len(encoded) > 8000:
                    raise RuntimeError("persistence_error")
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='succeeded',result_task_revision=?,safe_result_json=?,"
                    f"error_code=NULL,updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    new_revision,
                    encoded,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
                should_drain = True
                outcome = result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

        if terminal_error is not None:
            raise ValueError(terminal_error)
        if should_drain:
            self._drain_best_effort()
        if not isinstance(outcome, dict):
            raise RuntimeError("persistence_error")
        return outcome

    def complete_product_task_update_proposal(
        self,
        *,
        request_id: str,
        task_id: str,
        actor: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        connection = self._connect()
        terminal_error: str | None = None
        outcome: dict[str, Any] | None = None
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT schedule_id,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise KeyError("requirement_task_not_found")
            if task[1] == "provisioning":
                raise ValueError("requirement_task_provisioning")

            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) WHERE request_id=?",
                request_id,
            )
            request_row = c.fetchone()
            if request_row is None:
                raise KeyError("requirement_product_request_invalid")
            request = self._product_request_dict(request_row)
            if (
                request["operation"] != "task_update"
                or request["task_id"] != task_id
                or not request["schedule_version_id"]
            ):
                raise ValueError("requirement_product_request_invalid")
            if request["state"] == "succeeded":
                result = request["safe_result"]
                if not isinstance(result, dict):
                    raise RuntimeError("persistence_error")
                connection.commit()
                return result
            if request["state"] == "failed_terminal":
                raise ValueError(
                    request["error_code"] or "requirement_product_request_terminal"
                )
            if request["state"] not in {"reserved", "in_progress", "failed_recoverable"}:
                raise ValueError("requirement_product_request_invalid")

            if (
                task[0] != request["schedule_id"]
                or int(task[2]) != int(request["base_task_revision"])
            ):
                terminal_error = "requirement_task_conflict"

            if terminal_error is not None:
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='failed_terminal',safe_result_json=NULL,error_code=?,"
                    f"updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    terminal_error,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
            else:
                c.execute(
                    f"SELECT schedule_version_id,schedule_id,version_number,config_sha256,status "
                    f"FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
                    f"WHERE schedule_version_id=?",
                    request["schedule_version_id"],
                )
                version = c.fetchone()
                if (
                    version is None
                    or version[1] != request["schedule_id"]
                    or version[4] != "draft"
                ):
                    raise ValueError("requirement_task_update_incomplete")

                result = {
                    "mode": "schedule_proposal",
                    "task_id": task_id,
                    "base_task_revision": int(request["base_task_revision"]),
                    "schedule_id": request["schedule_id"],
                    "schedule_version_id": version[0],
                    "version_number": int(version[2]),
                    "config_sha256": version[3],
                    "status": "draft",
                }
                encoded = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if len(encoded) > 8000:
                    raise RuntimeError("persistence_error")
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='succeeded',result_task_revision=NULL,safe_result_json=?,"
                    f"error_code=NULL,updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    encoded,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
                outcome = result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

        if terminal_error is not None:
            raise ValueError(terminal_error)
        if not isinstance(outcome, dict):
            raise RuntimeError("persistence_error")
        return outcome

    def reserve_product_input_replacement(
        self,
        *,
        task_id: str,
        principal_kind: str,
        principal_id: str,
        idempotency_key: str,
        request_sha256: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        """Reserve an immutable source snapshot CAS anchor and import identities."""
        if (
            not task_id or principal_kind != "user" or not principal_id
            or len(principal_id) > 128 or not idempotency_key
            or len(idempotency_key) > 128 or len(request_sha256) != 64
            or any(char not in "0123456789abcdef" for char in request_sha256)
        ):
            raise ValueError("requirement_product_request_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE principal_kind=? AND principal_id=? AND operation='input_replace' AND idempotency_key=?",
                principal_kind, principal_id, idempotency_key,
            )
            existing = c.fetchone()
            if existing is not None:
                result = self._product_request_dict(existing)
                if result["request_sha256"] != request_sha256:
                    raise ValueError("requirement_idempotency_conflict")
                connection.commit()
                return result

            c.execute(
                f"SELECT task_id,schedule_id,source_id,product_state "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise KeyError("requirement_task_not_found")
            if task[3] == "provisioning":
                raise ValueError("requirement_task_provisioning")
            if task[3] not in {"active", "disabled"}:
                raise ValueError("requirement_product_task_conflict")
            c.execute(
                f"SELECT active_snapshot_id FROM [{self.requirement_schema}].[requirement_sets] "
                f"WITH (UPDLOCK,HOLDLOCK) WHERE source_id=?",
                task[2],
            )
            set_row = c.fetchone()
            if set_row is None or not set_row[0]:
                raise RuntimeError("persistence_error")
            base_snapshot_id = set_row[0]
            request_id, run_id, snapshot_id = _id("preq"), _id("run"), _id("snap")
            c.execute(
                f"INSERT INTO {self.t}.[requirement_product_requests]("
                "request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,"
                "task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,"
                "batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,"
                "created_at,updated_at,completed_at"
                ") VALUES (?,?,?,?,?,?,'reserved',?,?,?,?,?,NULL,NULL,NULL,NULL,?,NULL,NULL,?,?,NULL)",
                request_id, principal_kind, principal_id, "input_replace",
                idempotency_key, request_sha256, task_id, task[2], run_id,
                snapshot_id, task[1], base_snapshot_id, now_utc, now_utc,
            )
            connection.commit()
            return {
                "request_id": request_id, "principal_kind": principal_kind,
                "principal_id": principal_id, "operation": "input_replace",
                "idempotency_key": idempotency_key, "request_sha256": request_sha256,
                "state": "reserved", "task_id": task_id, "source_id": task[2],
                "import_run_id": run_id, "snapshot_id": snapshot_id,
                "schedule_id": task[1], "schedule_version_id": None,
                "batch_run_id": None, "base_task_revision": None,
                "result_task_revision": None, "base_snapshot_id": base_snapshot_id,
                "safe_result_json": None, "safe_result": None, "error_code": None,
                "created_at": now_utc, "updated_at": now_utc, "completed_at": None,
            }
        except Exception as exc:
            connection.rollback()
            if _is_unique_key_conflict(exc):
                read_connection = self._connect()
                try:
                    c = read_connection.cursor()
                    c.execute(
                        f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                        f"FROM {self.t}.[requirement_product_requests] "
                        f"WHERE principal_kind=? AND principal_id=? AND operation='input_replace' AND idempotency_key=?",
                        principal_kind, principal_id, idempotency_key,
                    )
                    raced = c.fetchone()
                    if raced is None:
                        raise RuntimeError("persistence_error")
                    result = self._product_request_dict(raced)
                    if result["request_sha256"] != request_sha256:
                        raise ValueError("requirement_idempotency_conflict")
                    return result
                except Exception as read_exc:
                    raise _safe_error(read_exc) from read_exc
                finally:
                    read_connection.close()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def mark_product_input_replacement_in_progress(
        self, request_id: str, *, now_utc: datetime
    ) -> None:
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='in_progress',updated_at=? "
                f"WHERE request_id=? AND operation='input_replace' "
                f"AND state IN ('reserved','failed_recoverable')",
                now_utc, request_id,
            )
            c.execute(
                f"SELECT state FROM {self.t}.[requirement_product_requests] "
                f"WITH (UPDLOCK,HOLDLOCK) WHERE request_id=? AND operation='input_replace'",
                request_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("requirement_product_request_invalid")
            if row[0] not in {"in_progress", "succeeded"}:
                raise ValueError("requirement_product_request_terminal")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def complete_product_input_replacement(
        self, *, request_id: str, task_id: str, now_utc: datetime,
    ) -> dict[str, Any]:
        """Finalize ledger only after proving committed import IDs, including delayed replay."""
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE request_id=? AND operation='input_replace'",
                request_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("requirement_product_request_invalid")
            request = self._product_request_dict(row)
            if request["task_id"] != task_id:
                raise ValueError("requirement_product_request_invalid")
            if request["state"] == "succeeded":
                result = request["safe_result"]
                if not isinstance(result, dict):
                    raise RuntimeError("persistence_error")
                connection.commit()
                return result
            if request["state"] == "failed_terminal":
                raise ValueError(request["error_code"] or "requirement_product_request_terminal")
            if request["state"] not in {"reserved", "in_progress", "failed_recoverable"}:
                raise ValueError("requirement_product_request_invalid")

            c.execute(
                f"SELECT r.source_id,r.status,s.snapshot_id "
                f"FROM [{self.requirement_schema}].[import_runs] r WITH (HOLDLOCK) "
                f"LEFT JOIN [{self.requirement_schema}].[requirement_set_snapshots] s WITH (HOLDLOCK) "
                f"ON s.import_run_id=r.import_run_id WHERE r.import_run_id=?",
                request["import_run_id"],
            )
            imported = tuple(c.fetchall())
            if len(imported) != 1 or imported[0] != (
                request["source_id"], "committed", request["snapshot_id"]
            ):
                raise ValueError("requirement_product_input_incomplete")
            result = {
                "task_id": request["task_id"],
                "source_id": request["source_id"],
                "import_run_id": request["import_run_id"],
                "snapshot_id": request["snapshot_id"],
                "status": "committed",
            }
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='succeeded',safe_result_json=?,error_code=NULL,"
                f"updated_at=?,completed_at=? WHERE request_id=? "
                f"AND state IN ('reserved','in_progress','failed_recoverable')",
                json.dumps(result, separators=(",", ":"), sort_keys=True),
                now_utc, now_utc, request_id,
            )
            if getattr(c, "rowcount", 1) != 1:
                raise ValueError("requirement_product_request_invalid")
            connection.commit()
            return result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def reserve_product_task_version_activation(
        self,
        *,
        task_id: str,
        schedule_version_id: str,
        principal_kind: str,
        principal_id: str,
        idempotency_key: str,
        request_sha256: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        if (
            not task_id
            or not schedule_version_id
            or principal_kind != "user"
            or not principal_id
            or len(principal_id) > 128
            or not idempotency_key
            or len(idempotency_key) > 128
            or len(request_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in request_sha256)
        ):
            raise ValueError("requirement_product_request_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE principal_kind=? AND principal_id=? "
                f"AND operation='task_version_activate' AND idempotency_key=?",
                principal_kind,
                principal_id,
                idempotency_key,
            )
            existing = c.fetchone()
            if existing is not None:
                result = self._product_request_dict(existing)
                if result["request_sha256"] != request_sha256:
                    raise ValueError("requirement_idempotency_conflict")
                connection.commit()
                return result

            # Match the finalizer's relative lock order so concurrent
            # activation keys cannot deadlock on Task/origin or Version/origin.
            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise KeyError("requirement_task_not_found")
            if task[4] == "provisioning":
                raise ValueError("requirement_task_provisioning")
            if task[4] not in {"active", "disabled"}:
                raise ValueError("requirement_product_task_conflict")

            c.execute(
                f"SELECT schedule_id,status "
                f"FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE schedule_version_id=?",
                schedule_version_id,
            )
            version = c.fetchone()
            if (
                version is None
                or version[0] != task[1]
                or version[1] != "draft"
            ):
                raise ValueError("requirement_task_version_invalid")

            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE operation='task_update' AND task_id=? AND schedule_version_id=? "
                f"AND state='succeeded'",
                task_id,
                schedule_version_id,
            )
            origin_rows = tuple(c.fetchall())
            if len(origin_rows) != 1:
                raise ValueError("requirement_task_version_invalid")
            origin = self._product_request_dict(origin_rows[0])
            origin_result = origin.get("safe_result")
            if (
                origin["base_task_revision"] is None
                or origin["result_task_revision"] is not None
                or not isinstance(origin_result, dict)
                or origin_result.get("mode") != "schedule_proposal"
                or origin_result.get("task_id") != task_id
                or origin_result.get("schedule_id") != origin["schedule_id"]
                or origin_result.get("schedule_version_id") != schedule_version_id
                or int(origin_result.get("base_task_revision", -1))
                != int(origin["base_task_revision"])
            ):
                raise ValueError("requirement_task_version_invalid")
            if (
                task[1] != origin["schedule_id"]
                or task[2] != origin["source_id"]
            ):
                raise ValueError("requirement_product_task_conflict")

            request_id = _id("preq")
            base_revision = int(origin["base_task_revision"])
            c.execute(
                f"INSERT INTO {self.t}.[requirement_product_requests]("
                "request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,"
                "task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,"
                "batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,"
                "created_at,updated_at,completed_at"
                ") VALUES (?,?,?,?,?,?,'reserved',?,?,NULL,NULL,?,?,NULL,?,NULL,NULL,NULL,NULL,?,?,NULL)",
                request_id,
                principal_kind,
                principal_id,
                "task_version_activate",
                idempotency_key,
                request_sha256,
                task_id,
                task[2],
                task[1],
                schedule_version_id,
                base_revision,
                now_utc,
                now_utc,
            )
            connection.commit()
            return {
                "request_id": request_id,
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "operation": "task_version_activate",
                "idempotency_key": idempotency_key,
                "request_sha256": request_sha256,
                "state": "reserved",
                "task_id": task_id,
                "source_id": task[2],
                "import_run_id": None,
                "snapshot_id": None,
                "schedule_id": task[1],
                "schedule_version_id": schedule_version_id,
                "batch_run_id": None,
                "base_task_revision": base_revision,
                "result_task_revision": None,
                "base_snapshot_id": None,
                "safe_result_json": None,
                "safe_result": None,
                "error_code": None,
                "created_at": now_utc,
                "updated_at": now_utc,
                "completed_at": None,
            }
        except Exception as exc:
            connection.rollback()
            if _is_unique_key_conflict(exc):
                read_connection = self._connect()
                try:
                    cursor = read_connection.cursor()
                    cursor.execute(
                        f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                        f"FROM {self.t}.[requirement_product_requests] "
                        f"WHERE principal_kind=? AND principal_id=? "
                        f"AND operation='task_version_activate' AND idempotency_key=?",
                        principal_kind,
                        principal_id,
                        idempotency_key,
                    )
                    raced = cursor.fetchone()
                    if raced is None:
                        raise RuntimeError("persistence_error")
                    result = self._product_request_dict(raced)
                    if result["request_sha256"] != request_sha256:
                        raise ValueError("requirement_idempotency_conflict")
                    return result
                except Exception as read_exc:
                    raise _safe_error(read_exc) from read_exc
                finally:
                    read_connection.close()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def mark_product_task_version_activation_in_progress(
        self, request_id: str, *, now_utc: datetime
    ) -> None:
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='in_progress',updated_at=? "
                f"WHERE request_id=? AND operation='task_version_activate' "
                f"AND state IN ('reserved','failed_recoverable')",
                now_utc,
                request_id,
            )
            c.execute(
                f"SELECT state FROM {self.t}.[requirement_product_requests] "
                f"WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE request_id=? AND operation='task_version_activate'",
                request_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("requirement_product_request_invalid")
            if row[0] not in {"in_progress", "succeeded"}:
                raise ValueError("requirement_product_request_terminal")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def finalize_product_task_version_activation(
        self,
        *,
        request_id: str,
        task_id: str,
        schedule_version_id: str,
        actor: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        connection = self._connect()
        should_drain = False
        terminal_error: str | None = None
        outcome: dict[str, Any] | None = None
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE request_id=?",
                request_id,
            )
            request_row = c.fetchone()
            if request_row is None:
                raise KeyError("requirement_product_request_invalid")
            request = self._product_request_dict(request_row)
            if (
                request["operation"] != "task_version_activate"
                or request["task_id"] != task_id
                or request["schedule_version_id"] != schedule_version_id
            ):
                raise ValueError("requirement_product_request_invalid")
            if request["state"] == "succeeded":
                result = request["safe_result"]
                if not isinstance(result, dict):
                    raise RuntimeError("persistence_error")
                connection.commit()
                return result
            if request["state"] == "failed_terminal":
                raise ValueError(
                    request["error_code"] or "requirement_product_request_terminal"
                )
            if request["state"] not in {"reserved", "in_progress", "failed_recoverable"}:
                raise ValueError("requirement_product_request_invalid")

            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise KeyError("requirement_task_not_found")
            if task[4] == "provisioning":
                raise ValueError("requirement_task_provisioning")
            if (
                task[1] != request["schedule_id"]
                or task[2] != request["source_id"]
                or task[4] not in {"active", "disabled"}
            ):
                raise ValueError("requirement_product_task_conflict")

            c.execute(
                f"SELECT enabled,active_version_id,next_run_at "
                f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE schedule_id=?",
                task[1],
            )
            schedule = c.fetchone()
            if schedule is None:
                raise KeyError("schedule_not_found")
            if task[3] == "recurring":
                if (task[4] == "active") != bool(schedule[0]):
                    raise RuntimeError("persistence_error")
            elif task[4] != "active" or bool(schedule[0]):
                raise RuntimeError("persistence_error")

            c.execute(
                f"SELECT schedule_id,version_number,status "
                f"FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE schedule_version_id=?",
                schedule_version_id,
            )
            version = c.fetchone()
            if version is None or version[0] != task[1]:
                terminal_error = "requirement_task_version_invalid"

            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE operation='task_update' AND task_id=? AND schedule_version_id=? "
                f"AND state='succeeded'",
                task_id,
                schedule_version_id,
            )
            origin_rows = tuple(c.fetchall())
            if len(origin_rows) != 1:
                terminal_error = "requirement_task_version_invalid"
                origin = None
            else:
                origin = self._product_request_dict(origin_rows[0])
                origin_result = origin.get("safe_result")
                if (
                    origin["base_task_revision"] is None
                    or origin["result_task_revision"] is not None
                    or not isinstance(origin_result, dict)
                    or origin_result.get("mode") != "schedule_proposal"
                    or origin_result.get("task_id") != task_id
                    or origin_result.get("schedule_id") != task[1]
                    or origin_result.get("schedule_version_id") != schedule_version_id
                    or int(origin_result.get("base_task_revision", -1))
                    != int(origin["base_task_revision"])
                    or int(request["base_task_revision"])
                    != int(origin["base_task_revision"])
                ):
                    terminal_error = "requirement_task_version_invalid"

            if (
                terminal_error is None
                and int(task[5]) != int(request["base_task_revision"])
            ):
                terminal_error = "requirement_task_conflict"
            if (
                terminal_error is None
                and version is not None
                and version[2] != "draft"
            ):
                terminal_error = "requirement_task_version_invalid"

            if terminal_error is not None:
                if (
                    terminal_error == "requirement_task_conflict"
                    and version is not None
                    and version[2] == "draft"
                    and origin is not None
                ):
                    c.execute(
                        f"UPDATE {self.t}.[requirement_schedule_versions] "
                        f"SET status='retired',retired_at=? "
                        f"WHERE schedule_version_id=? AND status='draft'",
                        now_utc,
                        schedule_version_id,
                    )
                    if getattr(c, "rowcount", 1) != 1:
                        raise ValueError("requirement_task_version_invalid")
                    self._enqueue_audit_event(
                        c,
                        self._audit_event(
                            "requirement_schedule.version_retired",
                            actor,
                            task[1],
                            schedule_version_id=schedule_version_id,
                            payload={"version_number": int(version[1])},
                            created_at=now_utc,
                        ),
                    )
                    should_drain = True
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='failed_terminal',safe_result_json=NULL,error_code=?,"
                    f"updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    terminal_error,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
            else:
                approval = self._approve_version_locked(
                    c,
                    schedule_id=task[1],
                    schedule_version_id=schedule_version_id,
                    actor=actor,
                    now_utc=now_utc,
                )
                new_revision = int(task[5]) + 1
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_tasks] "
                    f"SET revision=?,updated_by=?,updated_at=? "
                    f"WHERE task_id=? AND revision=?",
                    new_revision,
                    actor,
                    now_utc,
                    task_id,
                    request["base_task_revision"],
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_task_conflict")
                self._enqueue_audit_event(
                    c,
                    self._audit_event(
                        "requirement.task.updated",
                        actor,
                        task[1],
                        schedule_version_id=schedule_version_id,
                        payload={
                            "task_id": task_id,
                            "revision": new_revision,
                            "operation": "task_version_activate",
                        },
                        created_at=now_utc,
                    ),
                )

                next_run_at = approval["next_run_at"]
                result = {
                    "mode": "schedule_activation",
                    "task_id": task_id,
                    "task_revision": new_revision,
                    "execution_kind": task[3],
                    "product_state": task[4],
                    "schedule_id": task[1],
                    "schedule_version_id": schedule_version_id,
                    "version_number": int(approval["version_number"]),
                    "status": "approved",
                    "enabled": bool(approval["enabled"]),
                    "next_run_at": (
                        next_run_at.isoformat()
                        if isinstance(next_run_at, datetime)
                        else next_run_at
                    ),
                }
                encoded = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if len(encoded) > 8000:
                    raise RuntimeError("persistence_error")
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='succeeded',result_task_revision=?,safe_result_json=?,"
                    f"error_code=NULL,updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    new_revision,
                    encoded,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
                should_drain = True
                outcome = result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

        if should_drain:
            self._drain_best_effort()
        if terminal_error is not None:
            raise ValueError(terminal_error)
        if not isinstance(outcome, dict):
            raise RuntimeError("persistence_error")
        return outcome

    def is_product_owned_schedule(self, schedule_id: str) -> bool:
        if not schedule_id:
            return False
        task_rows = self._query(
            f"SELECT TOP 1 task_id FROM {self.t}.[requirement_product_tasks] "
            f"WHERE schedule_id=?",
            schedule_id,
        )
        if task_rows:
            return True
        request_rows = self._query(
            f"SELECT TOP 1 request_id FROM {self.t}.[requirement_product_requests] "
            f"WHERE operation='task_create' AND schedule_id=?",
            schedule_id,
        )
        return bool(request_rows)

    def _guard_low_level_schedule_mutation_locked(self, cursor, schedule_id: str) -> None:
        cursor.execute(
            f"SELECT TOP 1 task_id FROM {self.t}.[requirement_product_tasks] "
            f"WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
            schedule_id,
        )
        if cursor.fetchone() is not None:
            raise ValueError("requirement_product_owned_schedule")
        cursor.execute(
            f"SELECT TOP 1 request_id FROM {self.t}.[requirement_product_requests] "
            f"WITH (UPDLOCK,HOLDLOCK) "
            f"WHERE operation='task_create' AND schedule_id=?",
            schedule_id,
        )
        if cursor.fetchone() is not None:
            raise ValueError("requirement_product_owned_schedule")

    def finalize_one_time_product_task_create(
        self,
        *,
        request_id: str,
        task_id: str,
        actor: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) WHERE request_id=?",
                request_id,
            )
            request_row = c.fetchone()
            if request_row is None:
                raise KeyError("requirement_product_request_invalid")
            request = self._product_request_dict(request_row)
            if request["operation"] != "task_create" or request["task_id"] != task_id:
                raise ValueError("requirement_product_request_invalid")
            if request["state"] == "succeeded":
                result = request["safe_result"]
                if not isinstance(result, dict):
                    raise RuntimeError("persistence_error")
                connection.commit()
                return result
            if request["state"] == "failed_terminal":
                raise ValueError(request["error_code"] or "requirement_product_request_terminal")
            if request["state"] not in {"reserved", "in_progress", "failed_recoverable"}:
                raise ValueError("requirement_product_request_invalid")

            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise ValueError("requirement_product_create_incomplete")
            if (
                task[1] != request["schedule_id"]
                or task[2] != request["source_id"]
                or task[3] != "once"
                or task[4] != "provisioning"
                or int(task[5]) != 1
            ):
                raise ValueError("requirement_product_task_conflict")

            c.execute(
                f"SELECT requirement_set_id,enabled,active_version_id,next_run_at "
                f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                request["schedule_id"],
            )
            schedule = c.fetchone()
            if (
                schedule is None
                or bool(schedule[1])
                or schedule[2] != request["schedule_version_id"]
                or schedule[3] is not None
            ):
                raise ValueError("requirement_product_create_incomplete")

            c.execute(
                f"SELECT status,run_policy FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE schedule_id=? AND schedule_version_id=?",
                request["schedule_id"], request["schedule_version_id"],
            )
            version = c.fetchone()
            if version is None or version[0] != "approved":
                raise ValueError("requirement_product_create_incomplete")

            c.execute(
                f"SELECT active_snapshot_id FROM [{self.requirement_schema}].[requirement_sets] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE requirement_set_id=?",
                schedule[0],
            )
            set_row = c.fetchone()
            if set_row is None or set_row[0] != request["snapshot_id"]:
                raise ValueError("requirement_product_create_incomplete")

            trigger_request_id = f"product-create:{request_id}"
            selection_time = request["created_at"]
            if (
                not isinstance(selection_time, datetime)
                or selection_time.tzinfo is None
            ):
                raise RuntimeError("persistence_error")
            materialized = self._materialize_locked(
                c,
                request["schedule_id"],
                request["schedule_version_id"],
                version[1],
                TriggerIdentity("manual", trigger_request_id=trigger_request_id),
                now_utc,
                actor,
                selection_time=selection_time,
            )
            batch_run_id = materialized.run["batch_run_id"]
            result = {
                "task_id": task_id,
                "source_id": request["source_id"],
                "import_run_id": request["import_run_id"],
                "snapshot_id": request["snapshot_id"],
                "schedule_id": request["schedule_id"],
                "schedule_version_id": request["schedule_version_id"],
                "batch_run_id": batch_run_id,
                "task_revision": 1,
            }
            encoded_result = json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if len(encoded_result) > 8000:
                raise RuntimeError("persistence_error")
            c.execute(
                f"UPDATE {self.t}.[requirement_product_tasks] "
                f"SET product_state='active',updated_by=?,updated_at=? "
                f"WHERE task_id=? AND product_state='provisioning' AND revision=1",
                actor, now_utc, task_id,
            )
            c.execute(
                f"UPDATE {self.t}.[requirement_product_requests] "
                f"SET state='succeeded',batch_run_id=?,result_task_revision=1,safe_result_json=?,"
                f"error_code=NULL,updated_at=?,completed_at=? WHERE request_id=?",
                batch_run_id, encoded_result, now_utc, now_utc, request_id,
            )
            connection.commit()
            return result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def finalize_recurring_product_task_create(
        self,
        *,
        request_id: str,
        task_id: str,
        actor: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        connection = self._connect()
        should_drain = False
        terminal_error: str | None = None
        outcome: dict[str, Any] | None = None
        try:
            c = connection.cursor()
            c.execute(
                f"SELECT request_id,principal_kind,principal_id,operation,idempotency_key,request_sha256,state,task_id,source_id,import_run_id,snapshot_id,schedule_id,schedule_version_id,batch_run_id,base_task_revision,result_task_revision,base_snapshot_id,safe_result_json,error_code,created_at,updated_at,completed_at "
                f"FROM {self.t}.[requirement_product_requests] WITH (UPDLOCK,HOLDLOCK) WHERE request_id=?",
                request_id,
            )
            request_row = c.fetchone()
            if request_row is None:
                raise KeyError("requirement_product_request_invalid")
            request = self._product_request_dict(request_row)
            if request["operation"] != "task_create" or request["task_id"] != task_id:
                raise ValueError("requirement_product_request_invalid")
            if request["state"] == "succeeded":
                result = request["safe_result"]
                if not isinstance(result, dict):
                    raise RuntimeError("persistence_error")
                connection.commit()
                return result
            if request["state"] == "failed_terminal":
                raise ValueError(
                    request["error_code"] or "requirement_product_request_terminal"
                )
            if request["state"] not in {"reserved", "in_progress", "failed_recoverable"}:
                raise ValueError("requirement_product_request_invalid")

            c.execute(
                f"SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision "
                f"FROM {self.t}.[requirement_product_tasks] WITH (UPDLOCK,HOLDLOCK) WHERE task_id=?",
                task_id,
            )
            task = c.fetchone()
            if task is None:
                raise ValueError("requirement_product_create_incomplete")
            if (
                task[1] != request["schedule_id"]
                or task[2] != request["source_id"]
                or task[3] != "recurring"
                or task[4] != "provisioning"
                or int(task[5]) != 1
            ):
                raise ValueError("requirement_product_task_conflict")

            c.execute(
                f"SELECT requirement_set_id,enabled,active_version_id,next_run_at "
                f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                request["schedule_id"],
            )
            schedule = c.fetchone()
            if (
                schedule is None
                or bool(schedule[1])
                or schedule[2] != request["schedule_version_id"]
                or schedule[3] is not None
            ):
                raise ValueError("requirement_product_create_incomplete")

            c.execute(
                f"SELECT status,timezone,recurrence_json,run_policy,model,config_sha256 "
                f"FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE schedule_id=? AND schedule_version_id=?",
                request["schedule_id"],
                request["schedule_version_id"],
            )
            version = c.fetchone()
            if version is None or version[0] != "approved":
                raise ValueError("requirement_product_create_incomplete")
            config = self._validate_persisted_config(
                version[1], version[2], version[3], version[4], version[5]
            )

            c.execute(
                f"SELECT active_snapshot_id FROM [{self.requirement_schema}].[requirement_sets] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE requirement_set_id=?",
                schedule[0],
            )
            set_row = c.fetchone()
            if set_row is None or set_row[0] != request["snapshot_id"]:
                raise ValueError("requirement_product_create_incomplete")

            next_run_at = next_occurrence(
                config.recurrence,
                config.timezone,
                now_utc,
            )
            c.execute(
                f"SELECT TOP 1 1 "
                f"FROM [{self.requirement_schema}].[requirement_snapshot_items] i WITH (HOLDLOCK) "
                f"JOIN [{self.requirement_schema}].[requirement_versions] v WITH (HOLDLOCK) "
                f"ON v.requirement_version_id=i.requirement_version_id "
                f"WHERE i.snapshot_id=? AND (v.expires_at IS NULL OR v.expires_at>?)",
                request["snapshot_id"],
                next_run_at,
            )
            if c.fetchone() is None:
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='failed_terminal',safe_result_json=NULL,"
                    f"error_code='requirement_product_no_selectable_first_run',"
                    f"updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
                terminal_error = "requirement_product_no_selectable_first_run"
            else:
                c.execute(
                    f"UPDATE {self.t}.[requirement_schedules] "
                    f"SET enabled=1,next_run_at=?,updated_by=?,updated_at=? "
                    f"WHERE schedule_id=? AND enabled=0 AND active_version_id=? AND next_run_at IS NULL",
                    next_run_at,
                    actor,
                    now_utc,
                    request["schedule_id"],
                    request["schedule_version_id"],
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_create_incomplete")
                self._enqueue_audit_event(
                    c,
                    self._audit_event(
                        "requirement_schedule.enabled",
                        actor,
                        request["schedule_id"],
                        schedule_version_id=request["schedule_version_id"],
                        created_at=now_utc,
                    ),
                )

                result = {
                    "task_id": task_id,
                    "source_id": request["source_id"],
                    "import_run_id": request["import_run_id"],
                    "snapshot_id": request["snapshot_id"],
                    "schedule_id": request["schedule_id"],
                    "schedule_version_id": request["schedule_version_id"],
                    "next_run_at": next_run_at.isoformat(),
                    "task_revision": 1,
                }
                encoded_result = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if len(encoded_result) > 8000:
                    raise RuntimeError("persistence_error")

                c.execute(
                    f"UPDATE {self.t}.[requirement_product_tasks] "
                    f"SET product_state='active',updated_by=?,updated_at=? "
                    f"WHERE task_id=? AND product_state='provisioning' "
                    f"AND execution_kind='recurring' AND revision=1",
                    actor,
                    now_utc,
                    task_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_task_conflict")
                c.execute(
                    f"UPDATE {self.t}.[requirement_product_requests] "
                    f"SET state='succeeded',batch_run_id=NULL,result_task_revision=1,"
                    f"safe_result_json=?,error_code=NULL,updated_at=?,completed_at=? "
                    f"WHERE request_id=? AND state IN ('reserved','in_progress','failed_recoverable')",
                    encoded_result,
                    now_utc,
                    now_utc,
                    request_id,
                )
                if getattr(c, "rowcount", 1) != 1:
                    raise ValueError("requirement_product_request_invalid")
                connection.commit()
                should_drain = True
                outcome = result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()
        if terminal_error is not None:
            raise ValueError(terminal_error)
        if should_drain:
            self._drain_best_effort()
        if not isinstance(outcome, dict):
            raise RuntimeError("persistence_error")
        return outcome

    def _query(self, sql: str, *params) -> list[dict[str, Any]]:
        connection = self._connect()
        try: c = connection.cursor(); c.execute(sql, *params); return self._rows(c)
        except Exception as exc: raise _safe_error(exc) from exc
        finally: connection.close()

    def list_schedules(self, *, enabled: bool | None = None, requirement_set_id: str | None = None, limit: int = 50, offset: int = 0):
        limit = max(1, min(int(limit), 100)); offset = max(0, int(offset)); where=[]; params=[]
        if enabled is not None: where.append("enabled=?"); params.append(enabled)
        if requirement_set_id is not None: where.append("requirement_set_id=?"); params.append(requirement_set_id)
        clause = " WHERE " + " AND ".join(where) if where else ""
        return self._query(f"SELECT schedule_id,name,requirement_set_id,enabled,active_version_id,next_run_at,created_by,created_at,updated_by,updated_at FROM {self.t}.[requirement_schedules]{clause} ORDER BY created_at,schedule_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", *params, offset, limit)
    def get_schedule(self, schedule_id: str):
        rows = self._query(f"SELECT schedule_id,name,requirement_set_id,enabled,active_version_id,next_run_at,created_by,created_at,updated_by,updated_at FROM {self.t}.[requirement_schedules] WHERE schedule_id=?", schedule_id)
        if not rows: raise KeyError("schedule_not_found")
        result = rows[0]
        result["versions"] = self._query(f"SELECT schedule_version_id,version_number,timezone,run_policy,model,config_sha256,status,created_by,created_at,approved_by,approved_at,retired_at FROM {self.t}.[requirement_schedule_versions] WHERE schedule_id=? ORDER BY version_number DESC", schedule_id)
        return result

    def get_active_schedule_config(self, schedule_id: str) -> dict[str, Any]:
        rows = self._query(
            f"SELECT s.active_version_id,v.timezone,v.recurrence_json,v.run_policy,v.model,v.config_sha256,v.status "
            f"FROM {self.t}.[requirement_schedules] s "
            f"LEFT JOIN {self.t}.[requirement_schedule_versions] v "
            f"ON v.schedule_version_id=s.active_version_id "
            f"WHERE s.schedule_id=?",
            schedule_id,
        )
        if not rows:
            raise KeyError("schedule_not_found")
        row = rows[0]
        if not row["active_version_id"] or row["status"] != "approved":
            raise ValueError("schedule_version_not_approved")
        config = self._validate_persisted_config(
            row["timezone"],
            row["recurrence_json"],
            row["run_policy"],
            row["model"],
            row["config_sha256"],
        )
        return {
            "schedule_version_id": row["active_version_id"],
            "config": config,
        }

    def get_schedule_version_config(
        self, schedule_id: str, schedule_version_id: str
    ) -> dict[str, Any]:
        rows = self._query(
            f"SELECT schedule_version_id,schedule_id,version_number,timezone,recurrence_json,"
            f"run_policy,model,config_sha256,status,created_by,created_at "
            f"FROM {self.t}.[requirement_schedule_versions] "
            f"WHERE schedule_id=? AND schedule_version_id=?",
            schedule_id,
            schedule_version_id,
        )
        if not rows:
            raise KeyError("schedule_version_not_found")
        row = rows[0]
        config = self._validate_persisted_config(
            row["timezone"],
            row["recurrence_json"],
            row["run_policy"],
            row["model"],
            row["config_sha256"],
        )
        return {
            "schedule_version_id": row["schedule_version_id"],
            "schedule_id": row["schedule_id"],
            "version_number": int(row["version_number"]),
            "config": config,
            "config_sha256": row["config_sha256"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }

    def rename_schedule(self, schedule_id: str, name: str, actor: str):
        return self._rename_schedule(
            schedule_id, name, actor, guard_low_level=False
        )

    def guarded_rename_schedule(self, schedule_id: str, name: str, actor: str):
        return self._rename_schedule(
            schedule_id, name, actor, guard_low_level=True
        )

    def _rename_schedule(
        self,
        schedule_id: str,
        name: str,
        actor: str,
        *,
        guard_low_level: bool,
    ):
        if not name.strip():
            raise ValueError("schedule_name_invalid")
        connection = self._connect()
        now = _now()
        try:
            c = connection.cursor()
            if guard_low_level:
                self._guard_low_level_schedule_mutation_locked(c, schedule_id)
            c.execute(
                f"SELECT enabled FROM {self.t}.[requirement_schedules] "
                f"WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                schedule_id,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("schedule_not_found")
            if bool(row[0]):
                raise ValueError("schedule_enabled")
            c.execute(
                f"UPDATE {self.t}.[requirement_schedules] "
                f"SET name=?,updated_by=?,updated_at=? WHERE schedule_id=?",
                name.strip(),
                actor,
                now,
                schedule_id,
            )
            self._enqueue_audit_event(
                c,
                self._audit_event(
                    "requirement_schedule.updated",
                    actor,
                    schedule_id,
                    payload={"field": "name"},
                    created_at=now,
                ),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()
        self._drain_best_effort()
        return self.get_schedule(schedule_id)

    @staticmethod
    def canonical_config(config: ScheduleVersionCreate) -> tuple[str, str]:
        document = {"schema_version": 1, "timezone": config.timezone, "recurrence": config.recurrence.as_dict(), "run_policy": config.run_policy.value, "model": config.model}
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return encoded, hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def _validate_persisted_config(cls, timezone_name: str, recurrence_json: str,
                                   run_policy: str, model: str,
                                   config_sha256: str | None = None) -> ScheduleVersionCreate:
        try:
            document = json.loads(recurrence_json)
            recurrence_document = document["recurrence"] if "recurrence" in document else document
            config = ScheduleVersionCreate(timezone_name, RecurrenceSpec.validate(recurrence_document),
                                           RunPolicy(run_policy), model)
            encoded, digest = cls.canonical_config(config)
            if config_sha256 is not None and (recurrence_json != encoded or config_sha256 != digest):
                raise ValueError("recurrence_invalid")
            return config
        except (KeyError, TypeError, json.JSONDecodeError, ValueError):
            raise ValueError("recurrence_invalid") from None

    def create_version(
        self,
        *,
        schedule_id: str,
        config: ScheduleVersionCreate,
        actor: str,
        schedule_version_id: str | None = None,
    ) -> dict[str, Any]:
        return self._create_version(
            schedule_id=schedule_id,
            config=config,
            actor=actor,
            schedule_version_id=schedule_version_id,
            guard_low_level=False,
        )

    def guarded_create_version(
        self,
        *,
        schedule_id: str,
        config: ScheduleVersionCreate,
        actor: str,
    ) -> dict[str, Any]:
        return self._create_version(
            schedule_id=schedule_id,
            config=config,
            actor=actor,
            schedule_version_id=None,
            guard_low_level=True,
        )

    def _create_version(
        self,
        *,
        schedule_id: str,
        config: ScheduleVersionCreate,
        actor: str,
        schedule_version_id: str | None,
        guard_low_level: bool,
    ) -> dict[str, Any]:
        # Enforce domain invariants even for callers which bypass FastAPI validation.
        config = ScheduleVersionCreate(
            config.timezone,
            RecurrenceSpec.validate(config.recurrence.as_dict()),
            config.run_policy,
            config.model,
        )
        encoded, digest = self.canonical_config(config)
        connection = self._connect()
        now = _now()
        vid = schedule_version_id or _id("sv")
        replayed: dict[str, Any] | None = None
        try:
            c = connection.cursor()
            if guard_low_level:
                self._guard_low_level_schedule_mutation_locked(c, schedule_id)
            c.execute(
                f"SELECT schedule_id FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                schedule_id,
            )
            if c.fetchone() is None:
                raise KeyError("schedule_not_found")
            if schedule_version_id is not None:
                c.execute(
                    f"SELECT schedule_version_id,schedule_id,version_number,timezone,recurrence_json,run_policy,model,config_sha256,status,created_by,created_at FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_version_id=?",
                    vid,
                )
                existing = c.fetchone()
                if existing is not None:
                    if existing[1] != schedule_id or existing[7] != digest:
                        raise RuntimeError("persistence_error")
                    persisted = self._validate_persisted_config(
                        existing[3], existing[4], existing[5], existing[6], existing[7]
                    )
                    replayed = {
                        "schedule_version_id": existing[0],
                        "schedule_id": existing[1],
                        "version_number": int(existing[2]),
                        "timezone": persisted.timezone,
                        "recurrence": persisted.recurrence.as_dict(),
                        "run_policy": persisted.run_policy.value,
                        "model": persisted.model,
                        "config_sha256": existing[7],
                        "status": existing[8],
                        "created_by": existing[9],
                        "created_at": existing[10],
                    }
                    connection.commit()
            if replayed is None:
                c.execute(
                    f"SELECT COALESCE(MAX(version_number),0)+1 FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                    schedule_id,
                )
                number = int(c.fetchone()[0])
                c.execute(
                    f"INSERT INTO {self.t}.[requirement_schedule_versions](schedule_version_id,schedule_id,version_number,timezone,recurrence_json,run_policy,model,config_sha256,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,'draft',?,?)",
                    vid, schedule_id, number, config.timezone, encoded,
                    config.run_policy.value, config.model, digest, actor, now,
                )
                self._enqueue_audit_event(
                    c,
                    self._audit_event(
                        "requirement_schedule.version_created",
                        actor,
                        schedule_id,
                        schedule_version_id=vid,
                        payload={"version_number": number},
                        created_at=now,
                    ),
                )
                connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()
        if replayed is not None:
            return replayed
        self._drain_best_effort()
        return {
            "schedule_version_id": vid,
            "schedule_id": schedule_id,
            "version_number": number,
            "timezone": config.timezone,
            "recurrence": config.recurrence.as_dict(),
            "run_policy": config.run_policy.value,
            "model": config.model,
            "config_sha256": digest,
            "status": "draft",
            "created_by": actor,
            "created_at": now,
        }

    def _approve_version_locked(
        self,
        c,
        *,
        schedule_id: str,
        schedule_version_id: str,
        actor: str,
        now_utc: datetime,
    ) -> dict[str, Any]:
        c.execute(
            f"SELECT enabled,active_version_id,next_run_at "
            f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) "
            f"WHERE schedule_id=?",
            schedule_id,
        )
        schedule = c.fetchone()
        if schedule is None:
            raise KeyError("schedule_not_found")
        c.execute(
            f"SELECT version_number,status,timezone,recurrence_json,run_policy,model,config_sha256 "
            f"FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) "
            f"WHERE schedule_id=? AND schedule_version_id=?",
            schedule_id,
            schedule_version_id,
        )
        version = c.fetchone()
        if version is None:
            raise KeyError("schedule_version_not_found")
        (
            version_number,
            status,
            timezone_name,
            recurrence_json,
            run_policy,
            model,
            config_sha256,
        ) = version
        if status == "approved" and schedule[1] == schedule_version_id:
            return {
                "schedule_version_id": schedule_version_id,
                "status": "approved",
                "version_number": int(version_number),
                "enabled": bool(schedule[0]),
                "next_run_at": schedule[2],
            }
        if status != "draft":
            raise ValueError("schedule_version_not_approved")

        config = self._validate_persisted_config(
            timezone_name,
            recurrence_json,
            run_policy,
            model,
            config_sha256,
        )
        due = (
            next_occurrence(config.recurrence, config.timezone, now_utc)
            if bool(schedule[0])
            else None
        )
        if schedule[1] and schedule[1] != schedule_version_id:
            c.execute(
                f"UPDATE {self.t}.[requirement_schedule_versions] "
                f"SET status='retired',retired_at=? "
                f"WHERE schedule_version_id=? AND status='approved'",
                now_utc,
                schedule[1],
            )
            if getattr(c, "rowcount", 1) != 1:
                raise RuntimeError("persistence_error")
        c.execute(
            f"UPDATE {self.t}.[requirement_schedule_versions] "
            f"SET status='approved',approved_by=?,approved_at=? "
            f"WHERE schedule_version_id=? AND status='draft'",
            actor,
            now_utc,
            schedule_version_id,
        )
        if getattr(c, "rowcount", 1) != 1:
            raise ValueError("schedule_version_not_approved")
        c.execute(
            f"UPDATE {self.t}.[requirement_schedules] "
            f"SET active_version_id=?,next_run_at=?,updated_by=?,updated_at=? "
            f"WHERE schedule_id=?",
            schedule_version_id,
            due,
            actor,
            now_utc,
            schedule_id,
        )
        if getattr(c, "rowcount", 1) != 1:
            raise RuntimeError("persistence_error")
        self._enqueue_audit_event(
            c,
            self._audit_event(
                "requirement_schedule.version_approved",
                actor,
                schedule_id,
                schedule_version_id=schedule_version_id,
                payload={"version_number": int(version_number)},
                created_at=now_utc,
            ),
        )
        return {
            "schedule_version_id": schedule_version_id,
            "status": "approved",
            "version_number": int(version_number),
            "enabled": bool(schedule[0]),
            "next_run_at": due,
        }

    def approve_version(
        self,
        *,
        schedule_id: str,
        version_number: int,
        actor: str,
        now_utc: datetime,
    ):
        return self._approve_version(
            schedule_id=schedule_id,
            version_number=version_number,
            actor=actor,
            now_utc=now_utc,
            guard_low_level=False,
        )

    def guarded_approve_version(
        self,
        *,
        schedule_id: str,
        version_number: int,
        actor: str,
        now_utc: datetime,
    ):
        return self._approve_version(
            schedule_id=schedule_id,
            version_number=version_number,
            actor=actor,
            now_utc=now_utc,
            guard_low_level=True,
        )

    def _approve_version(
        self,
        *,
        schedule_id: str,
        version_number: int,
        actor: str,
        now_utc: datetime,
        guard_low_level: bool,
    ):
        connection = self._connect()
        try:
            c = connection.cursor()
            if guard_low_level:
                self._guard_low_level_schedule_mutation_locked(c, schedule_id)
            # Resolve immutable version identity without retaining an update lock.
            # _approve_version_locked() owns the mutation lock order and always
            # acquires Schedule before target Version, matching set_enabled().
            c.execute(
                f"SELECT schedule_version_id "
                f"FROM {self.t}.[requirement_schedule_versions] "
                f"WHERE schedule_id=? AND version_number=?",
                schedule_id,
                version_number,
            )
            row = c.fetchone()
            if row is None:
                raise KeyError("schedule_version_not_found")
            result = self._approve_version_locked(
                c,
                schedule_id=schedule_id,
                schedule_version_id=row[0],
                actor=actor,
                now_utc=now_utc,
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()
        self._drain_best_effort()
        return {
            "schedule_version_id": result["schedule_version_id"],
            "status": result["status"],
            "version_number": result["version_number"],
        }

    def set_enabled(
        self, *, schedule_id: str, enabled: bool, actor: str, now_utc: datetime
    ):
        return self._set_enabled(
            schedule_id=schedule_id,
            enabled=enabled,
            actor=actor,
            now_utc=now_utc,
            guard_low_level=False,
        )

    def guarded_set_enabled(
        self, *, schedule_id: str, enabled: bool, actor: str, now_utc: datetime
    ):
        return self._set_enabled(
            schedule_id=schedule_id,
            enabled=enabled,
            actor=actor,
            now_utc=now_utc,
            guard_low_level=True,
        )

    def _set_enabled(
        self,
        *,
        schedule_id: str,
        enabled: bool,
        actor: str,
        now_utc: datetime,
        guard_low_level: bool,
    ):
        connection = self._connect()
        try:
            c = connection.cursor()
            if guard_low_level:
                self._guard_low_level_schedule_mutation_locked(c, schedule_id)
            c.execute(
                f"SELECT enabled,active_version_id,next_run_at "
                f"FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) "
                f"WHERE schedule_id=?",
                schedule_id,
            )
            schedule = c.fetchone()
            if schedule is None:
                raise KeyError("schedule_not_found")
            if bool(schedule[0]) == bool(enabled):
                connection.commit()
                return {
                    "schedule_id": schedule_id,
                    "enabled": bool(enabled),
                    "next_run_at": schedule[2],
                }
            due = None
            if enabled:
                if not schedule[1]:
                    raise ValueError("schedule_version_not_approved")
                c.execute(
                    f"SELECT status,timezone,recurrence_json,run_policy,model,config_sha256 "
                    f"FROM {self.t}.[requirement_schedule_versions] "
                    f"WITH (UPDLOCK,HOLDLOCK) WHERE schedule_version_id=?",
                    schedule[1],
                )
                version = c.fetchone()
                if version is None or version[0] != "approved":
                    raise ValueError("schedule_version_not_approved")
                config = self._validate_persisted_config(
                    version[1], version[2], version[3], version[4], version[5]
                )
                due = next_occurrence(
                    config.recurrence, config.timezone, now_utc
                )
            c.execute(
                f"UPDATE {self.t}.[requirement_schedules] "
                f"SET enabled=?,next_run_at=?,updated_by=?,updated_at=? "
                f"WHERE schedule_id=?",
                bool(enabled),
                due,
                actor,
                now_utc,
                schedule_id,
            )
            action = (
                "requirement_schedule.enabled"
                if enabled
                else "requirement_schedule.disabled"
            )
            self._enqueue_audit_event(
                c, self._audit_event(action, actor, schedule_id, created_at=now_utc)
            )
            connection.commit()
            self._drain_best_effort()
            return {
                "schedule_id": schedule_id,
                "enabled": bool(enabled),
                "next_run_at": due,
            }
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    def list_pending_audit_events(self, limit: int) -> tuple[ScheduleAuditEvent, ...]:
        limit = max(1, min(int(limit), 100))
        rows = self._query(
            f"SELECT TOP (?) audit_event_id,action,actor,schedule_id,schedule_version_id,safe_payload_json,created_at FROM {self.t}.[requirement_schedule_audit_outbox] WHERE delivered_at IS NULL ORDER BY created_at,audit_event_id",
            limit,
        )
        return tuple(ScheduleAuditEvent(row["audit_event_id"], row["action"], row["actor"], row["schedule_id"], row["schedule_version_id"], json.loads(row["safe_payload_json"]), row["created_at"]) for row in rows)

    def mark_audit_delivered(self, event_id: str, at: datetime) -> bool:
        return self._update_audit_delivery(
            f"UPDATE {self.t}.[requirement_schedule_audit_outbox] SET delivery_attempt_count=delivery_attempt_count+1,last_delivery_attempt_at=?,last_delivery_error_code=NULL,delivered_at=? WHERE audit_event_id=? AND delivered_at IS NULL",
            at, at, event_id,
        )

    def mark_audit_failed(self, event_id: str, at: datetime) -> bool:
        return self._update_audit_delivery(
            f"UPDATE {self.t}.[requirement_schedule_audit_outbox] SET delivery_attempt_count=delivery_attempt_count+1,last_delivery_attempt_at=?,last_delivery_error_code='audit_sink_write_failed' WHERE audit_event_id=? AND delivered_at IS NULL",
            at, event_id,
        )

    def _update_audit_delivery(self, sql: str, *params) -> bool:
        connection = self._connect()
        try:
            cursor = connection.cursor(); cursor.execute(sql, *params)
            changed = getattr(cursor, "rowcount", 1) == 1
            connection.commit(); return changed
        except Exception as exc:
            connection.rollback(); raise _safe_error(exc) from exc
        finally:
            connection.close()

    def claim_due(self, *, now_utc: datetime, actor: str):
        """Claim at most one latest due occurrence and advance it atomically."""
        connection = self._connect()
        race_identity = None
        try:
            c = connection.cursor()
            c.execute(f"SELECT TOP 1 s.schedule_id,s.active_version_id,s.next_run_at,v.timezone,v.recurrence_json,v.run_policy FROM {self.t}.[requirement_schedules] s WITH (UPDLOCK,HOLDLOCK) JOIN {self.t}.[requirement_schedule_versions] v WITH (UPDLOCK,HOLDLOCK) ON v.schedule_version_id=s.active_version_id WHERE s.enabled=1 AND s.next_run_at<=? AND v.status='approved' ORDER BY s.next_run_at,s.schedule_id", now_utc)
            row = c.fetchone()
            if row is None: connection.commit(); return None
            schedule_id, version_id, persisted_due, timezone_name, recurrence_json, policy = row
            document = json.loads(recurrence_json); spec = RecurrenceSpec.validate(document.get("recurrence", document))
            latest, following = coalesce_latest(spec, timezone_name, persisted_due, now_utc)
            race_identity = (schedule_id, version_id, latest, following)
            materialized = self._materialize_locked(
                c,
                schedule_id,
                version_id,
                policy,
                TriggerIdentity("scheduled", latest),
                now_utc,
                actor,
                selection_time=latest,
            )
            run_id = materialized.run["batch_run_id"]
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET next_run_at=?,updated_by=?,updated_at=? WHERE schedule_id=? AND active_version_id=?", following, actor, now_utc, schedule_id, version_id); connection.commit()
            return {"batch_run_id": run_id, "schedule_id": schedule_id, "schedule_version_id": version_id, "scheduled_for": latest, "next_run_at": following}
        except Exception as exc:
            connection.rollback()
            if race_identity is not None and _is_scheduled_occurrence_conflict(exc):
                schedule_id, version_id, latest, following = race_identity
                read_connection = self._connect()
                try:
                    cursor = read_connection.cursor()
                    cursor.execute(f"SELECT batch_run_id FROM {self.t}.[requirement_batch_runs] WHERE schedule_id=? AND scheduled_for=? AND trigger_type='scheduled'", schedule_id, latest)
                    existing = cursor.fetchone()
                    cursor.execute(f"SELECT next_run_at FROM {self.t}.[requirement_schedules] WHERE schedule_id=?", schedule_id)
                    schedule = cursor.fetchone()
                    if existing is None or schedule is None:
                        raise RuntimeError("persistence_error")
                    return {"batch_run_id": existing[0], "schedule_id": schedule_id, "schedule_version_id": version_id, "scheduled_for": latest, "next_run_at": schedule[0]}
                except Exception as read_exc:
                    raise _safe_error(read_exc) from read_exc
                finally:
                    read_connection.close()
            raise _safe_error(exc) from exc
        finally: connection.close()

    def _materialize_locked(
        self,
        c,
        schedule_id: str,
        version_id: str,
        policy: str,
        trigger: TriggerIdentity,
        now_utc: datetime,
        actor: str,
        *,
        selection_time: datetime | None = None,
    ) -> MaterializedRun:
        selection_at = selection_time or now_utc
        if selection_at.tzinfo is None:
            raise ValueError("datetime_not_aware")
        identity_value = trigger.scheduled_for if trigger.trigger_type == "scheduled" else trigger.trigger_request_id
        identity_column = "scheduled_for" if trigger.trigger_type == "scheduled" else "trigger_request_id"
        c.execute(f"SELECT batch_run_id FROM {self.t}.[requirement_batch_runs] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=? AND {identity_column}=? AND trigger_type=?", schedule_id, identity_value, trigger.trigger_type)
        existing = c.fetchone()
        if existing:
            return MaterializedRun({"batch_run_id": existing[0], "schedule_id": schedule_id}, ())
        c.execute(f"SELECT active_snapshot_id FROM [{self.requirement_schema}].[requirement_sets] WITH (UPDLOCK,HOLDLOCK) WHERE requirement_set_id=(SELECT requirement_set_id FROM {self.t}.[requirement_schedules] WHERE schedule_id=?)", schedule_id); snapshot_row = c.fetchone()
        snapshot_id = snapshot_row[0] if snapshot_row else None; run_id = _id("br")
        if snapshot_id is None:
            phase1a_batch_id = f"reqrun-{run_id}"
            c.execute(f"INSERT INTO {self.t}.[requirement_batch_runs](batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,run_policy,phase1a_batch_id,state,selected_count,skipped_count,success_count,failure_count,error_code,error_message,deadline_elapsed_during_execution,created_by,created_at,materialized_at,updated_at) VALUES (?,?,?,?,?,?,NULL,?,?,'blocked_no_snapshot',0,0,0,0,'no_active_snapshot','No active Requirement snapshot',0,?,?,?,?)", run_id, schedule_id, version_id, trigger.trigger_type, trigger.trigger_request_id, trigger.scheduled_for, policy, phase1a_batch_id, actor, now_utc, now_utc, now_utc)
            return MaterializedRun({"batch_run_id": run_id, "phase1a_batch_id": phase1a_batch_id, "schedule_id": schedule_id, "schedule_version_id": version_id, "snapshot_id": None, "state": "blocked_no_snapshot"}, ())
        c.execute(f"SELECT i.requirement_id,i.requirement_version_id,v.version_number,i.source_order,v.expires_at,r.external_item_id FROM [{self.requirement_schema}].[requirement_snapshot_items] i WITH (HOLDLOCK) JOIN [{self.requirement_schema}].[requirement_versions] v WITH (HOLDLOCK) ON v.requirement_version_id=i.requirement_version_id JOIN [{self.requirement_schema}].[requirements] r WITH (HOLDLOCK) ON r.requirement_id=i.requirement_id WHERE i.snapshot_id=? ORDER BY i.source_order", snapshot_id); source_items = tuple(c.fetchall())
        items = []
        for requirement_id, rv_id, rv_number, source_order, expires_at, external_item_id in source_items:
            c.execute(f"SELECT last_seen_requirement_version_id,last_seen_requirement_version_number,last_successful_requirement_version_id,last_successful_requirement_version_number FROM {self.t}.[requirement_schedule_item_state] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=? AND requirement_id=?", schedule_id, requirement_id); cp = c.fetchone()
            checkpoint = Checkpoint(*(cp or (None, None, None, None)))
            decision = evaluate_selection(policy, rv_id, int(rv_number), checkpoint, expires_at, selection_at)
            items.append({"run_item_id": _id("ri"), "requirement_id": requirement_id, "external_item_id": external_item_id, "requirement_version_id": rv_id, "requirement_version_number": int(rv_number), "source_order": int(source_order), "selection_status": "selected" if decision.selected else "skipped", "selection_reason": decision.reason, "expired_at_selection": decision.expired_at_selection})
        selected = sum(x["selection_status"] == "selected" for x in items); skipped = len(items) - selected
        phase1a_batch_id = f"reqrun-{run_id}"
        c.execute(f"INSERT INTO {self.t}.[requirement_batch_runs](batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,run_policy,phase1a_batch_id,state,selected_count,skipped_count,success_count,failure_count,deadline_elapsed_during_execution,created_by,created_at,materialized_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'handoff_pending',?,?,0,0,0,?,?,?,?)", run_id, schedule_id, version_id, trigger.trigger_type, trigger.trigger_request_id, trigger.scheduled_for, snapshot_id, policy, phase1a_batch_id, selected, skipped, actor, now_utc, now_utc, now_utc)
        for item in items:
            phase1a_task_id = item["external_item_id"] if item["selection_status"] == "selected" else None
            item["phase1a_task_id"] = phase1a_task_id
            c.execute(f"INSERT INTO {self.t}.[requirement_batch_run_items](run_item_id,batch_run_id,requirement_id,requirement_version_id,requirement_version_number,source_order,selection_status,selection_reason,phase1a_task_id,execution_state,expired_at_selection,expired_before_handoff,deadline_elapsed_during_execution,created_at,evaluated_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?)", item["run_item_id"], run_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], item["source_order"], item["selection_status"], item["selection_reason"], phase1a_task_id, "handoff_pending" if item["selection_status"] == "selected" else "not_selected", item["expired_at_selection"], now_utc, selection_at, now_utc)
            c.execute(f"MERGE {self.t}.[requirement_schedule_item_state] WITH (HOLDLOCK) AS t USING (SELECT ? schedule_id,? requirement_id) s ON t.schedule_id=s.schedule_id AND t.requirement_id=s.requirement_id WHEN MATCHED THEN UPDATE SET last_seen_requirement_version_id=?,last_seen_requirement_version_number=?,updated_at=? WHEN NOT MATCHED THEN INSERT(schedule_id,requirement_id,last_seen_requirement_version_id,last_seen_requirement_version_number,updated_at) VALUES (?,?,?,?,?);", schedule_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], now_utc, schedule_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], now_utc)
        run_state = "handoff_pending"
        if selected == 0:
            self._terminal_run_recompute(c, run_id, now_utc)
            run_state = "completed"
        return MaterializedRun({"batch_run_id": run_id, "phase1a_batch_id": phase1a_batch_id, "schedule_id": schedule_id, "schedule_version_id": version_id, "snapshot_id": snapshot_id, "state": run_state, "selected_count": selected, "skipped_count": skipped}, tuple(items))

    def materialize_run(
        self,
        *,
        schedule_id: str,
        trigger: TriggerIdentity,
        now_utc: datetime,
        actor: str,
    ) -> MaterializedRun:
        return self._materialize_run(
            schedule_id=schedule_id,
            trigger=trigger,
            now_utc=now_utc,
            actor=actor,
            guard_low_level=False,
        )

    def guarded_materialize_run(
        self,
        *,
        schedule_id: str,
        trigger: TriggerIdentity,
        now_utc: datetime,
        actor: str,
    ) -> MaterializedRun:
        return self._materialize_run(
            schedule_id=schedule_id,
            trigger=trigger,
            now_utc=now_utc,
            actor=actor,
            guard_low_level=True,
        )

    def _materialize_run(
        self,
        *,
        schedule_id: str,
        trigger: TriggerIdentity,
        now_utc: datetime,
        actor: str,
        guard_low_level: bool,
    ) -> MaterializedRun:
        connection = self._connect()
        try:
            c = connection.cursor()
            if guard_low_level:
                self._guard_low_level_schedule_mutation_locked(c, schedule_id)
            c.execute(
                f"SELECT active_version_id FROM {self.t}.[requirement_schedules] "
                f"WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?",
                schedule_id,
            )
            schedule = c.fetchone()
            if not schedule or not schedule[0]:
                raise KeyError("schedule_not_found")
            c.execute(
                f"SELECT run_policy,status FROM {self.t}.[requirement_schedule_versions] "
                f"WITH (UPDLOCK,HOLDLOCK) WHERE schedule_version_id=?",
                schedule[0],
            )
            version = c.fetchone()
            if not version or version[1] != "approved":
                raise ValueError("schedule_version_not_approved")
            result = self._materialize_locked(
                c,
                schedule_id,
                schedule[0],
                version[0],
                trigger,
                now_utc,
                actor,
            )
            connection.commit()
            return result
        except Exception as exc:
            connection.rollback()
            raise _safe_error(exc) from exc
        finally:
            connection.close()

    @staticmethod
    def _prove_lease(cursor, table: str, lease: LeaseProof) -> datetime:
        """Lock and prove coordinator authority using SQL Server's clock."""
        if lease.control_domain != CONTROL_DOMAIN:
            raise RuntimeError("lease_lost")
        now = _sql_utc_now(cursor)
        cursor.execute(
            f"SELECT owner_id,lease_token,fencing_generation,expires_at FROM {table}.[requirement_handoff_coordinator_leases] WITH (UPDLOCK,HOLDLOCK) WHERE control_domain=?",
            lease.control_domain,
        )
        row = cursor.fetchone()
        if (row is None or row[0] != lease.owner_id or row[1] != lease.lease_token
                or int(row[2]) != lease.fencing_generation or row[3] <= now):
            raise RuntimeError("lease_lost")
        return now

    @staticmethod
    def _handoff_source(row) -> dict[str, Any]:
        keys = ("run_item_id", "batch_run_id", "schedule_id", "schedule_version_id",
                "snapshot_id", "requirement_id", "requirement_version_id",
                "requirement_version_number", "resolved_prompt", "resolved_model",
                "deadline_at")
        return dict(zip(keys, row[:len(keys)], strict=True))

    def _terminal_run_recompute(self, cursor, batch_run_id: str, now: datetime) -> None:
        cursor.execute(
            f"SELECT execution_state,COUNT(*) FROM {self.t}.[requirement_batch_run_items] WITH (UPDLOCK,HOLDLOCK) WHERE batch_run_id=? AND selection_status='selected' GROUP BY execution_state",
            batch_run_id,
        )
        counts = {str(state): int(count) for state, count in cursor.fetchall()}
        success = counts.get("completed", 0)
        failures = sum(counts.get(state, 0) for state in ("failed", "recovery_required", "expired"))
        active = sum(counts.get(state, 0) for state in ("handoff_pending", "submitting", "pending", "running", "reconciling"))
        state = "completed" if active == 0 and failures == 0 else ("completed_with_failures" if active == 0 else "running")
        cursor.execute(
            f"UPDATE {self.t}.[requirement_batch_runs] SET success_count=?,failure_count=?,state=?,completed_at=CASE WHEN ?=0 THEN COALESCE(completed_at,?) ELSE NULL END,updated_at=? WHERE batch_run_id=?",
            success, failures, state, active, now, now, batch_run_id,
        )

    def prepare_next_handoff(self, *, lease: LeaseProof,
                             output_root_fingerprint: str,
                             now_utc: datetime | None = None) -> PreparedHandoff | None:
        """Fenced Prepare TX #1.  No transport or filesystem operation occurs here."""
        if len(output_root_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in output_root_fingerprint):
            raise ValueError("output_root_fingerprint_invalid")
        connection = self._connect()
        try:
            c = connection.cursor()
            db_now = self._prove_lease(c, self.t, lease)
            # now_utc is intentionally not expiry authority; it is accepted only for
            # compatibility with callers and deterministic tests. SQL time wins.
            c.execute(
                f"SELECT TOP 1 i.run_item_id,i.batch_run_id,r.schedule_id,r.schedule_version_id,r.snapshot_id,i.requirement_id,i.requirement_version_id,i.requirement_version_number,v.prompt_content,sv.model,v.expires_at,r.phase1a_output_root_fingerprint,r.state "
                f"FROM {self.t}.[requirement_batch_run_items] i WITH (UPDLOCK,READPAST,READCOMMITTEDLOCK) "
                f"JOIN {self.t}.[requirement_batch_runs] r WITH (UPDLOCK,HOLDLOCK) ON r.batch_run_id=i.batch_run_id "
                f"JOIN {self.t}.[requirement_schedule_versions] sv WITH (HOLDLOCK) ON sv.schedule_id=r.schedule_id AND sv.schedule_version_id=r.schedule_version_id "
                f"JOIN [{self.requirement_schema}].[requirement_snapshot_items] si WITH (HOLDLOCK) ON si.snapshot_id=r.snapshot_id AND si.requirement_id=i.requirement_id AND si.requirement_version_id=i.requirement_version_id "
                f"JOIN [{self.requirement_schema}].[requirements] q WITH (HOLDLOCK) ON q.requirement_id=i.requirement_id "
                f"JOIN [{self.requirement_schema}].[requirement_versions] v WITH (HOLDLOCK) ON v.requirement_id=i.requirement_id AND v.requirement_version_id=i.requirement_version_id AND v.version_number=i.requirement_version_number "
                f"WHERE i.selection_status='selected' AND i.execution_state='handoff_pending' AND r.state IN ('handoff_pending','running') ORDER BY i.created_at,i.run_item_id"
            )
            row = c.fetchone()
            if row is None:
                connection.commit()
                return None
            source = self._handoff_source(row)
            frozen_root, run_state = row[11], row[12]
            # Required second database-time check is deliberately after all identity locks.
            expiry_now = _sql_utc_now(c)
            if source["deadline_at"] is not None and source["deadline_at"] <= expiry_now:
                c.execute(
                    f"UPDATE {self.t}.[requirement_batch_run_items] SET execution_state='expired',expired_before_handoff=1,error_code='deadline_exceeded',error_message='deadline_exceeded',completed_at=?,updated_at=? WHERE run_item_id=? AND execution_state='handoff_pending'",
                    expiry_now, expiry_now, source["run_item_id"],
                )
                if getattr(c, "rowcount", 0) != 1: raise RuntimeError("handoff_state_conflict")
                self._terminal_run_recompute(c, source["batch_run_id"], expiry_now)
                event = self._audit_event("requirement_handoff.item_failed", lease.owner_id,
                    source["schedule_id"], schedule_version_id=source["schedule_version_id"],
                    payload={"batch_run_id": source["batch_run_id"], "run_item_id": source["run_item_id"],
                             "workflow_id": "report_v1", "fencing_generation": lease.fencing_generation,
                             "neutral_state": "expired", "category": "deadline_exceeded"}, created_at=expiry_now)
                self._enqueue_audit_event(c, event)
                connection.commit(); self._drain_best_effort(); return None
            if source["deadline_at"] is None:
                source["deadline_at"] = datetime.max.replace(tzinfo=timezone.utc, microsecond=0)
            if frozen_root is None:
                c.execute(
                    f"UPDATE {self.t}.[requirement_batch_runs] SET phase1a_output_root_fingerprint=?,updated_at=? WHERE batch_run_id=? AND phase1a_output_root_fingerprint IS NULL AND state=?",
                    output_root_fingerprint, expiry_now, source["batch_run_id"], run_state,
                )
                if getattr(c, "rowcount", 0) != 1: raise RuntimeError("output_root_bind_conflict")
                frozen_root = output_root_fingerprint
            if frozen_root != output_root_fingerprint:
                raise RuntimeError("output_root_fingerprint_mismatch")
            candidate = prepared_handoff(source["run_item_id"], build_execution_manifest(source))
            c.execute(
                f"SELECT submission_id,workflow_id,semantic_manifest_json,semantic_fingerprint,legacy_session_id FROM {self.t}.[requirement_handoff_submissions] WITH (UPDLOCK,HOLDLOCK) WHERE run_item_id=?",
                source["run_item_id"],
            )
            existing = c.fetchone()
            if existing is None:
                try:
                    c.execute(
                        f"INSERT INTO {self.t}.[requirement_handoff_submissions](submission_id,run_item_id,workflow_id,semantic_manifest_json,semantic_fingerprint,legacy_session_id,created_at,prepared_at) VALUES (?,?,?,?,?,?,?,?)",
                        candidate.submission_id, candidate.run_item_id, candidate.manifest.workflow_id,
                        candidate.semantic_manifest_json, candidate.semantic_fingerprint,
                        candidate.legacy_session_id, expiry_now, expiry_now,
                    )
                except Exception as exc:
                    # A unique-key race can only be accepted after the winner is
                    # visible and every immutable byte compares equal.
                    if not _is_unique_key_conflict(exc):
                        raise
                    c.execute(
                        f"SELECT submission_id,workflow_id,semantic_manifest_json,semantic_fingerprint,legacy_session_id FROM {self.t}.[requirement_handoff_submissions] WITH (UPDLOCK,HOLDLOCK) WHERE run_item_id=?",
                        source["run_item_id"],
                    )
                    existing = c.fetchone()
                    if existing is None: raise
            if existing is not None:
                stored_manifest = ExecutionManifest(**json.loads(existing[2]))
                stored = PreparedHandoff(source["run_item_id"], existing[0], stored_manifest,
                                         existing[2], existing[3], existing[4])
                if existing[1] != "report_v1": raise RuntimeError("submission_semantic_drift")
                verify_prepared(stored, candidate)
            c.execute(
                f"UPDATE {self.t}.[requirement_batch_run_items] SET execution_state='submitting',handoff_started_at=COALESCE(handoff_started_at,?),updated_at=? WHERE run_item_id=? AND execution_state='handoff_pending'",
                expiry_now, expiry_now, source["run_item_id"],
            )
            if getattr(c, "rowcount", 0) != 1: raise RuntimeError("handoff_state_conflict")
            c.execute(
                f"UPDATE {self.t}.[requirement_batch_runs] SET state='running',handoff_started_at=COALESCE(handoff_started_at,?),updated_at=? WHERE batch_run_id=? AND phase1a_output_root_fingerprint=?",
                expiry_now, expiry_now, source["batch_run_id"], frozen_root,
            )
            self._enqueue_audit_event(c, self._audit_event("requirement_handoff.prepared", lease.owner_id,
                source["schedule_id"], schedule_version_id=source["schedule_version_id"],
                payload={"batch_run_id": source["batch_run_id"], "run_item_id": source["run_item_id"],
                         "submission_id": candidate.submission_id, "workflow_id": "report_v1", "output_root_fingerprint": frozen_root,
                         "fencing_generation": lease.fencing_generation}, created_at=expiry_now))
            connection.commit()
            self._drain_best_effort()
            return candidate
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def _load_submission_locked(self, cursor, run_item_id: str):
        cursor.execute(
            f"SELECT s.submission_id,s.workflow_id,s.semantic_manifest_json,s.semantic_fingerprint,s.legacy_session_id,i.execution_state,i.remote_job_id,i.batch_run_id,r.schedule_id,r.schedule_version_id,r.phase1a_output_root_fingerprint "
            f"FROM {self.t}.[requirement_handoff_submissions] s WITH (UPDLOCK,HOLDLOCK) JOIN {self.t}.[requirement_batch_run_items] i WITH (UPDLOCK,HOLDLOCK) ON i.run_item_id=s.run_item_id JOIN {self.t}.[requirement_batch_runs] r WITH (UPDLOCK,HOLDLOCK) ON r.batch_run_id=i.batch_run_id WHERE s.run_item_id=?",
            run_item_id,
        )
        row = cursor.fetchone()
        if row is None: raise RuntimeError("submission_not_found")
        return row

    @staticmethod
    def _prepared_from_submission(run_item_id: str, row) -> PreparedHandoff:
        try: manifest = ExecutionManifest(**json.loads(row[2]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("submission_semantic_drift") from exc
        return PreparedHandoff(run_item_id, row[0], manifest, row[2], row[3], row[4])

    def acknowledge_submission(self, prepared: PreparedHandoff, handle: ExecutionHandle,
                               lease: LeaseProof, expected_state: str | None = None) -> None:
        if handle.submission_id != prepared.submission_id:
            raise RuntimeError("submission_semantic_drift")
        connection = self._connect()
        try:
            c = connection.cursor(); now = self._prove_lease(c, self.t, lease)
            row = self._load_submission_locked(c, prepared.run_item_id)
            verify_prepared(self._prepared_from_submission(prepared.run_item_id, row), prepared)
            allowed = {expected_state} if expected_state else {"submitting", "reconciling"}
            if row[5] not in allowed: raise RuntimeError("handoff_state_conflict")
            if row[6] is not None and row[6] != handle.remote_job_id:
                raise RuntimeError("remote_job_identity_conflict")
            c.execute(
                f"UPDATE {self.t}.[requirement_batch_run_items] SET remote_job_id=?,remote_job_state='pending',execution_state='pending',dispatched_at=COALESCE(dispatched_at,?),updated_at=? WHERE run_item_id=? AND execution_state=? AND (remote_job_id IS NULL OR remote_job_id=?)",
                handle.remote_job_id, now, now, prepared.run_item_id, row[5], handle.remote_job_id,
            )
            if getattr(c, "rowcount", 0) != 1: raise RuntimeError("handoff_state_conflict")
            c.execute(f"UPDATE {self.t}.[requirement_batch_runs] SET handed_off_at=COALESCE(handed_off_at,?),updated_at=? WHERE batch_run_id=?", now, now, row[7])
            self._enqueue_audit_event(c, self._audit_event("requirement_handoff.dispatched", lease.owner_id,
                row[8], schedule_version_id=row[9], payload={"batch_run_id": row[7],
                "run_item_id": prepared.run_item_id, "submission_id": prepared.submission_id, "workflow_id": "report_v1",
                "fencing_generation": lease.fencing_generation, "neutral_state": "pending"}, created_at=now))
            connection.commit(); self._drain_best_effort()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def mark_reconciling(self, run_item_id: str, lease: LeaseProof, category: str) -> None:
        connection = self._connect()
        try:
            c=connection.cursor(); now=self._prove_lease(c,self.t,lease); row=self._load_submission_locked(c,run_item_id)
            if row[5] not in {"submitting","pending","running","reconciling"}: raise RuntimeError("handoff_state_conflict")
            c.execute(f"UPDATE {self.t}.[requirement_batch_run_items] SET execution_state='reconciling',error_code=?,error_message=?,updated_at=? WHERE run_item_id=? AND execution_state=?",category,category,now,run_item_id,row[5])
            if getattr(c,"rowcount",0)!=1: raise RuntimeError("handoff_state_conflict")
            self._enqueue_audit_event(c,self._audit_event("requirement_handoff.reconciled",lease.owner_id,row[8],schedule_version_id=row[9],payload={"batch_run_id":row[7],"run_item_id":run_item_id,"submission_id":row[0],"workflow_id":"report_v1","fencing_generation":lease.fencing_generation,"neutral_state":"reconciling","category":category},created_at=now))
            connection.commit(); self._drain_best_effort()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def list_unfinished_handoffs(self, *, lease: LeaseProof, limit: int) -> list[dict[str, Any]]:
        limit=max(1,min(int(limit),100)); connection=self._connect()
        try:
            c=connection.cursor(); self._prove_lease(c,self.t,lease)
            c.execute(f"SELECT TOP (?) s.run_item_id,s.submission_id,s.workflow_id,s.semantic_manifest_json,s.semantic_fingerprint,s.legacy_session_id,i.remote_job_id,i.execution_state,i.batch_run_id,r.schedule_id,r.schedule_version_id,r.phase1a_output_root_fingerprint FROM {self.t}.[requirement_handoff_submissions] s JOIN {self.t}.[requirement_batch_run_items] i ON i.run_item_id=s.run_item_id JOIN {self.t}.[requirement_batch_runs] r ON r.batch_run_id=i.batch_run_id WHERE i.execution_state IN ('submitting','pending','running','reconciling') ORDER BY i.handoff_started_at,i.run_item_id",limit)
            result=[]
            for row in c.fetchall():
                prepared=self._prepared_from_submission(row[0],(row[1],row[2],row[3],row[4],row[5]))
                result.append({"run_item_id":row[0],"prepared":prepared,"remote_job_id":row[6],"execution_state":row[7],"batch_run_id":row[8],"schedule_id":row[9],"schedule_version_id":row[10],"output_root_fingerprint":row[11],"handle":ExecutionHandle(row[1],row[6]) if row[6] else None})
            connection.commit(); return result
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def record_reconciliation(self, row: dict[str,Any], status: ExecutionStatus,
                              lease: LeaseProof) -> None:
        if status.state == ExecutionState.COMPLETED:
            # Keep the item reconciling until artifact proof is durable.
            target="reconciling"
        else: target=status.state.value
        if target == "failed":
            return self.close_failed_or_recovery_item(lease, row["run_item_id"], "failed",
                status.safe_error.category.value if status.safe_error else "remote_execution_failed")
        if target == "recovery_required":
            return self.close_failed_or_recovery_item(lease,row["run_item_id"],"recovery_required",
                status.safe_error.category.value if status.safe_error else "reconciliation_unknown")
        connection=self._connect()
        try:
            c=connection.cursor(); now=self._prove_lease(c,self.t,lease); stored=self._load_submission_locked(c,row["run_item_id"])
            if stored[6] != row["remote_job_id"]: raise RuntimeError("remote_job_identity_conflict")
            if stored[5] not in {"pending","running","reconciling"}: raise RuntimeError("handoff_state_conflict")
            category=status.safe_error.category.value if status.safe_error else None
            c.execute(f"UPDATE {self.t}.[requirement_batch_run_items] SET execution_state=?,remote_job_state=?,error_code=?,error_message=?,remote_completed_at=CASE WHEN ?='reconciling' THEN COALESCE(remote_completed_at,?) ELSE remote_completed_at END,updated_at=? WHERE run_item_id=? AND execution_state=?",target,status.state.value,category,category,target,now,now,row["run_item_id"],stored[5])
            if getattr(c,"rowcount",0)!=1: raise RuntimeError("handoff_state_conflict")
            c.execute(f"UPDATE {self.t}.[requirement_batch_runs] SET reconciled_at=?,updated_at=? WHERE batch_run_id=?",now,now,stored[7])
            payload={"batch_run_id":stored[7],"run_item_id":row["run_item_id"],"submission_id":stored[0],"workflow_id":"report_v1","fencing_generation":lease.fencing_generation,"neutral_state":target}
            if category: payload["category"]=category
            self._enqueue_audit_event(c,self._audit_event("requirement_handoff.reconciled",lease.owner_id,stored[8],schedule_version_id=stored[9],payload=payload,created_at=now))
            connection.commit(); self._drain_best_effort()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def record_artifact_reconciled(self, *, lease: LeaseProof, run_item_id: str,
                                   relative_path: str, sha256: str,
                                   output_root_fingerprint: str) -> None:
        if (not relative_path or relative_path.startswith(("/","\\")) or ".." in relative_path.replace("\\","/").split("/")
                or len(sha256)!=64 or any(c not in "0123456789abcdef" for c in sha256)):
            raise ValueError("artifact_evidence_invalid")
        connection=self._connect()
        try:
            c=connection.cursor(); now=self._prove_lease(c,self.t,lease); row=self._load_submission_locked(c,run_item_id)
            if row[10] != output_root_fingerprint: raise RuntimeError("output_root_fingerprint_mismatch")
            if row[5] != "reconciling": raise RuntimeError("handoff_state_conflict")
            c.execute(f"UPDATE {self.t}.[requirement_batch_run_items] SET artifact_relative_path=?,artifact_sha256=?,artifact_reconciled_at=?,updated_at=? WHERE run_item_id=? AND execution_state='reconciling' AND remote_job_state='completed'",relative_path,sha256,now,now,run_item_id)
            if getattr(c,"rowcount",0)!=1: raise RuntimeError("artifact_proof_incomplete")
            self._enqueue_audit_event(c,self._audit_event("requirement_handoff.artifact_reconciled",lease.owner_id,row[8],schedule_version_id=row[9],payload={"batch_run_id":row[7],"run_item_id":run_item_id,"submission_id":row[0],"workflow_id":"report_v1","output_root_fingerprint":output_root_fingerprint,"fencing_generation":lease.fencing_generation,"artifact_sha256":sha256,"artifact_relative_path":relative_path},created_at=now))
            connection.commit(); self._drain_best_effort()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def close_completed_item(self, *, lease: LeaseProof, run_item_id: str,
                             output_root_fingerprint: str) -> None:
        connection=self._connect()
        try:
            c=connection.cursor(); now=self._prove_lease(c,self.t,lease)
            c.execute(f"SELECT i.batch_run_id,i.requirement_id,i.requirement_version_id,i.requirement_version_number,i.execution_state,i.remote_job_state,i.artifact_relative_path,i.artifact_sha256,i.artifact_reconciled_at,r.schedule_id,r.schedule_version_id,r.phase1a_output_root_fingerprint FROM {self.t}.[requirement_batch_run_items] i WITH (UPDLOCK,HOLDLOCK) JOIN {self.t}.[requirement_batch_runs] r WITH (UPDLOCK,HOLDLOCK) ON r.batch_run_id=i.batch_run_id WHERE i.run_item_id=?",run_item_id)
            row=c.fetchone()
            if row is None: raise RuntimeError("run_item_not_found")
            batch_run_id,requirement_id,version_id,version_number,state,remote_state,path,digest,reconciled_at,schedule_id,schedule_version_id,frozen=row
            if state == "completed": connection.commit(); return
            if state != "reconciling" or remote_state != "completed" or not path or not digest or reconciled_at is None:
                raise RuntimeError("artifact_proof_incomplete")
            if frozen != output_root_fingerprint: raise RuntimeError("output_root_fingerprint_mismatch")
            c.execute(f"SELECT submission_id FROM {self.t}.[requirement_handoff_submissions] WITH (UPDLOCK,HOLDLOCK) WHERE run_item_id=?",run_item_id)
            submission_row=c.fetchone()
            if submission_row is None: raise RuntimeError("submission_not_found")
            c.execute(f"SELECT last_successful_requirement_version_id,last_successful_requirement_version_number,last_successful_run_item_id FROM {self.t}.[requirement_schedule_item_state] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=? AND requirement_id=?",schedule_id,requirement_id)
            checkpoint=c.fetchone()
            outcome=checkpoint_outcome(checkpoint[1] if checkpoint else None,checkpoint[0] if checkpoint else None,int(version_number),version_id)
            c.execute(f"UPDATE {self.t}.[requirement_batch_run_items] SET execution_state='completed',error_code=NULL,error_message=NULL,completed_at=?,updated_at=? WHERE run_item_id=? AND execution_state='reconciling' AND remote_job_state='completed' AND artifact_relative_path IS NOT NULL AND artifact_sha256 IS NOT NULL AND artifact_reconciled_at IS NOT NULL",now,now,run_item_id)
            if getattr(c,"rowcount",0)!=1: raise RuntimeError("handoff_state_conflict")
            if outcome == "advance":
                c.execute(f"UPDATE {self.t}.[requirement_schedule_item_state] SET last_successful_requirement_version_id=?,last_successful_requirement_version_number=?,last_successful_run_item_id=?,last_successful_at=?,updated_at=? WHERE schedule_id=? AND requirement_id=?",version_id,version_number,run_item_id,now,now,schedule_id,requirement_id)
                if getattr(c,"rowcount",0)!=1: raise RuntimeError("checkpoint_not_found")
            self._terminal_run_recompute(c,batch_run_id,now)
            self._enqueue_audit_event(c,self._audit_event("requirement_handoff.item_completed",lease.owner_id,schedule_id,schedule_version_id=schedule_version_id,payload={"batch_run_id":batch_run_id,"run_item_id":run_item_id,"submission_id":submission_row[0],"workflow_id":"report_v1","fencing_generation":lease.fencing_generation,"neutral_state":"completed","artifact_sha256":digest,"artifact_relative_path":path},created_at=now))
            connection.commit(); self._drain_best_effort()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def close_failed_or_recovery_item(self, lease: LeaseProof, run_item_id: str,
                                      terminal_state: str, category: str) -> None:
        if terminal_state not in {"failed","recovery_required"}: raise ValueError("terminal_state_invalid")
        action="requirement_handoff.item_failed" if terminal_state=="failed" else "requirement_handoff.item_recovery_required"
        connection=self._connect()
        try:
            c=connection.cursor(); now=self._prove_lease(c,self.t,lease); row=self._load_submission_locked(c,run_item_id)
            if row[5] in {"completed","failed","recovery_required","expired"}:
                if row[5] == terminal_state: connection.commit(); return
                raise RuntimeError("handoff_state_conflict")
            c.execute(f"UPDATE {self.t}.[requirement_batch_run_items] SET execution_state=?,error_code=?,error_message=?,completed_at=?,updated_at=? WHERE run_item_id=? AND execution_state=?",terminal_state,category,category,now,now,run_item_id,row[5])
            if getattr(c,"rowcount",0)!=1: raise RuntimeError("handoff_state_conflict")
            self._terminal_run_recompute(c,row[7],now)
            if category in {"authentication_failed","authorization_failed"}:
                self._enqueue_audit_event(c,self._audit_event("requirement_handoff.remote_authorization_failed",lease.owner_id,row[8],schedule_version_id=row[9],payload={"batch_run_id":row[7],"run_item_id":run_item_id,"submission_id":row[0],"workflow_id":"report_v1","fencing_generation":lease.fencing_generation,"category":category},created_at=now))
            self._enqueue_audit_event(c,self._audit_event(action,lease.owner_id,row[8],schedule_version_id=row[9],payload={"batch_run_id":row[7],"run_item_id":run_item_id,"submission_id":row[0],"workflow_id":"report_v1","fencing_generation":lease.fencing_generation,"neutral_state":terminal_state,"category":category},created_at=now))
            connection.commit(); self._drain_best_effort()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    def list_batch_runs(self, *, schedule_id: str, limit: int=50, offset: int=0):
        limit=max(1,min(int(limit),100)); offset=max(0,int(offset))
        return self._query(f"SELECT batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,state,selected_count,skipped_count,success_count,failure_count,error_code,deadline_elapsed_during_execution,created_at,materialized_at,handoff_started_at,handed_off_at,reconciled_at,completed_at FROM {self.t}.[requirement_batch_runs] WHERE schedule_id=? ORDER BY created_at DESC,batch_run_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",schedule_id,offset,limit)

    def get_batch_run(self, *, schedule_id: str, batch_run_id: str):
        runs=self._query(f"SELECT batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,phase1a_output_root_fingerprint,state,selected_count,skipped_count,success_count,failure_count,error_code,deadline_elapsed_during_execution,created_at,materialized_at,handoff_started_at,handed_off_at,reconciled_at,completed_at FROM {self.t}.[requirement_batch_runs] WHERE schedule_id=? AND batch_run_id=?",schedule_id,batch_run_id)
        if not runs: raise KeyError("batch_run_not_found")
        runs[0]["items"]=self._query(f"SELECT run_item_id,requirement_id,requirement_version_id,requirement_version_number,source_order,selection_status,selection_reason,execution_state,remote_job_id,remote_job_state,error_code,expired_at_selection,expired_before_handoff,deadline_elapsed_during_execution,artifact_relative_path,artifact_sha256,handoff_started_at,dispatched_at,remote_completed_at,artifact_reconciled_at,completed_at FROM {self.t}.[requirement_batch_run_items] WHERE batch_run_id=? ORDER BY source_order",batch_run_id)
        return runs[0]

    def get_operator_artifact_evidence(self, *, batch_run_id: str, run_item_id: str):
        """Read the durable Batch/Run Item artifact identity without accepting path authority."""
        rows = self._query(
            f"SELECT r.batch_run_id,i.run_item_id,i.selection_status,i.remote_job_id,"
            f"i.artifact_relative_path,i.artifact_sha256,r.phase1a_output_root_fingerprint "
            f"FROM {self.t}.[requirement_batch_runs] r "
            f"JOIN {self.t}.[requirement_batch_run_items] i ON i.batch_run_id=r.batch_run_id "
            f"WHERE r.batch_run_id=? AND i.run_item_id=?",
            batch_run_id, run_item_id,
        )
        if not rows:
            raise KeyError("run_item_not_found")
        return rows[0]
