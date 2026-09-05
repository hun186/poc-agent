from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from .migrations import (
    SCHEMA_VERSION, bootstrap_schema_statements,
    canonical_v2_statements, classify_v1_catalog, migration_1_to_2_statements,
    validate_catalog_evidence, validate_schema_name, validation_queries,
)
from .models import MaterializedRun, RecurrenceSpec, ScheduleAuditEvent, ScheduleVersionCreate, TriggerIdentity
from .recurrence import next_occurrence
from .recurrence import coalesce_latest
from .policy import Checkpoint, evaluate_selection


def _now() -> datetime: return datetime.now(timezone.utc).replace(microsecond=0)
def _id(prefix: str) -> str: return f"{prefix}_{uuid4().hex}"


def _safe_error(exc: Exception) -> Exception:
    if isinstance(exc, (KeyError, ValueError)) and str(exc).strip("'") in {
        "schedule_not_found", "schedule_version_not_found", "schedule_enabled",
        "schedule_version_not_approved", "schedule_name_invalid", "recurrence_invalid",
        "timezone_naive", "timezone_invalid", "recurrence_second_precision_required",
        "schedule_model_invalid", "requirement_set_not_found",
    }: return exc
    return RuntimeError("persistence_error")


def _is_scheduled_occurrence_conflict(exc: Exception) -> bool:
    text = " ".join(str(part) for part in getattr(exc, "args", (exc,)))
    return ("23000" in text and ("2601" in text or "2627" in text)
            and "UX_schedule_run_scheduled" in text)


class ScheduleStore:
    """SQL Server Phase 1C authority. No method writes Phase 1B tables."""
    def __init__(self, registry, connection_ref: str, schema: str = "sra_schedule", requirement_schema: str = "sra_requirement"):
        self.registry = registry; self.connection_ref = connection_ref
        self.schema = validate_schema_name(schema); self.requirement_schema = validate_schema_name(requirement_schema)

    @property
    def t(self): return f"[{self.schema}]"

    def _connect(self):
        try: return self.registry.open_named_connection(self.connection_ref)
        except Exception as exc: raise RuntimeError("persistence_error") from exc

    @staticmethod
    def _audit_event(action: str, actor: str, schedule_id: str | None, *,
                     schedule_version_id: str | None = None, payload: dict[str, Any] | None = None,
                     created_at: datetime | None = None) -> ScheduleAuditEvent:
        allowed = {
            "requirement_schedule.created", "requirement_schedule.updated",
            "requirement_schedule.version_created", "requirement_schedule.version_approved",
            "requirement_schedule.enabled", "requirement_schedule.disabled",
        }
        if action not in allowed or not actor or len(actor) > 128:
            raise ValueError("audit_event_invalid")
        body = payload or {}
        forbidden = ("password", "token", "secret", "connection", "sql", "prompt", "traceback", "path", "body")
        if any(any(term in str(key).lower() for term in forbidden) for key in body):
            raise ValueError("audit_payload_invalid")
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(encoded) > 2000:
            raise ValueError("audit_payload_invalid")
        return ScheduleAuditEvent(_id("aud"), action, actor, schedule_id, schedule_version_id,
                                  body, created_at or _now())

    def _enqueue_audit_event(self, cursor, event: ScheduleAuditEvent) -> None:
        payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        cursor.execute(
            f"INSERT INTO {self.t}.[requirement_schedule_audit_outbox](audit_event_id,action,actor,schedule_id,schedule_version_id,payload_json,created_at,delivery_attempts) VALUES (?,?,?,?,?,?,?,0)",
            event.audit_event_id, event.action, event.actor, event.schedule_id,
            event.schedule_version_id, payload, event.created_at,
        )

    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def initialize(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            for sql in bootstrap_schema_statements(self.schema): cursor.execute(sql)
            cursor.execute(f"SELECT version FROM {self.t}.[schema_version] WITH (UPDLOCK,HOLDLOCK)"); row = cursor.fetchone()
            version = 0 if row is None else int(row[0])
            if version == 0:
                for sql in canonical_v2_statements(self.schema, self.requirement_schema): cursor.execute(sql)
            elif version == 1:
                shape = classify_v1_catalog(cursor, self.schema, self.requirement_schema)
                self._validate_legacy_configurations(cursor)
                if shape == "pr200_v1":
                    for sql in self._pr200_identity_repair_statements():
                        cursor.execute(sql)
                for sql in migration_1_to_2_statements(self.schema, shape):
                    cursor.execute(sql)
            elif version != SCHEMA_VERSION: raise RuntimeError("unsupported_requirement_schedule_schema")
            for name, sql, params, expected in validation_queries(self.schema, self.requirement_schema):
                cursor.execute(sql, *params); rows = tuple(cursor.fetchall())
                valid = validate_catalog_evidence(self.schema, expected, rows)
                if not valid: raise RuntimeError("unsupported_requirement_schedule_schema")
            if version == 0:
                if row is None: cursor.execute(f"INSERT INTO {self.t}.[schema_version](version) VALUES (?)", SCHEMA_VERSION)
                else: cursor.execute(f"UPDATE {self.t}.[schema_version] SET version=? WHERE version=0", SCHEMA_VERSION)
            elif version == 1:
                cursor.execute(f"UPDATE {self.t}.[schema_version] SET version=2 WHERE version=1")
                if getattr(cursor, "rowcount", 1) != 1:
                    raise RuntimeError("unsupported_requirement_schedule_schema")
                cursor.execute(f"SELECT version FROM {self.t}.[schema_version] WITH (UPDLOCK,HOLDLOCK)")
                migrated = cursor.fetchone()
                if migrated is None or int(migrated[0]) != SCHEMA_VERSION:
                    raise RuntimeError("unsupported_requirement_schedule_schema")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            if str(exc) == "unsupported_requirement_schedule_schema": raise
            raise _safe_error(exc) from exc
        finally: connection.close()

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
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_runs] WHERE phase1a_source_sha256 IS NOT NULL OR phase1a_output_root_fingerprint IS NOT NULL OR handoff_started_at IS NOT NULL OR handed_off_at IS NOT NULL OR reconciled_at IS NOT NULL OR success_count<>0 OR failure_count<>0) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_run_items] WHERE remote_job_id IS NOT NULL OR remote_job_state IS NOT NULL OR artifact_relative_path IS NOT NULL OR handoff_started_at IS NOT NULL OR dispatched_at IS NOT NULL OR remote_completed_at IS NOT NULL OR artifact_reconciled_at IS NOT NULL OR completed_at IS NOT NULL OR expired_before_handoff<>0 OR deadline_elapsed_during_execution<>0) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_runs] WHERE phase1a_batch_id<>N'phase1c-'+batch_run_id) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_run_items] WHERE (selection_status='selected' AND phase1a_task_id<>requirement_id) OR (selection_status='skipped' AND phase1a_task_id IS NOT NULL) OR selection_status NOT IN ('selected','skipped')) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"IF EXISTS(SELECT 1 FROM {s}.[requirement_batch_run_items] i LEFT JOIN {r}.[requirements] q ON q.requirement_id=i.requirement_id WHERE i.selection_status='selected' AND (q.requirement_id IS NULL OR LEN(q.external_item_id)>240)) THROW 51000,'unsupported_requirement_schedule_schema',1",
            f"UPDATE {s}.[requirement_batch_runs] SET phase1a_batch_id=N'reqrun-'+batch_run_id WHERE phase1a_batch_id=N'phase1c-'+batch_run_id",
            f"UPDATE i SET phase1a_task_id=q.external_item_id FROM {s}.[requirement_batch_run_items] i JOIN {r}.[requirements] q ON q.requirement_id=i.requirement_id WHERE i.selection_status='selected' AND i.phase1a_task_id=i.requirement_id",
        )

    def create_schedule(self, *, name: str, requirement_set_id: str, actor: str, schedule_id: str | None = None) -> dict[str, Any]:
        if not name.strip() or len(name) > 240: raise ValueError("schedule_name_invalid")
        sid, now = schedule_id or _id("sch"), _now(); connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(f"SELECT requirement_set_id FROM [{self.requirement_schema}].[requirement_sets] WHERE requirement_set_id=?", requirement_set_id)
            # Real SQL must prove the set. Lightweight recording fakes have no result contract.
            row = c.fetchone()
            if row is None: raise KeyError("requirement_set_not_found")
            c.execute(f"INSERT INTO {self.t}.[requirement_schedules](schedule_id,name,requirement_set_id,enabled,active_version_id,next_run_at,created_by,created_at,updated_by,updated_at) VALUES (?,?,?,0,NULL,NULL,?,?,?,?)", sid, name.strip(), requirement_set_id, actor, now, actor, now)
            self._enqueue_audit_event(c, self._audit_event("requirement_schedule.created", actor, sid, payload={"requirement_set_id": requirement_set_id}, created_at=now))
            connection.commit()
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
        return {"schedule_id": sid, "name": name.strip(), "requirement_set_id": requirement_set_id, "enabled": False, "active_version_id": None, "next_run_at": None, "created_by": actor, "created_at": now, "updated_by": actor, "updated_at": now}

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

    def rename_schedule(self, schedule_id: str, name: str, actor: str):
        if not name.strip(): raise ValueError("schedule_name_invalid")
        connection = self._connect(); now = _now()
        try:
            c = connection.cursor(); c.execute(f"SELECT enabled FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); row=c.fetchone()
            if row is None: raise KeyError("schedule_not_found")
            if bool(row[0]): raise ValueError("schedule_enabled")
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET name=?,updated_by=?,updated_at=? WHERE schedule_id=?", name.strip(), actor, now, schedule_id)
            self._enqueue_audit_event(c, self._audit_event("requirement_schedule.updated", actor, schedule_id, payload={"field": "name"}, created_at=now))
            connection.commit()
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
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
                                           run_policy, model)
            encoded, digest = cls.canonical_config(config)
            if config_sha256 is not None and (recurrence_json != encoded or config_sha256 != digest):
                raise ValueError("recurrence_invalid")
            return config
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("recurrence_invalid") from None

    def create_version(self, *, schedule_id: str, config: ScheduleVersionCreate, actor: str) -> dict[str, Any]:
        # Enforce domain invariants even for callers which bypass FastAPI validation.
        config = ScheduleVersionCreate(config.timezone, RecurrenceSpec.validate(config.recurrence.as_dict()), config.run_policy, config.model)
        encoded, digest = self.canonical_config(config); connection = self._connect(); now = _now(); vid = _id("sv")
        try:
            c = connection.cursor(); c.execute(f"SELECT schedule_id FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id)
            if c.fetchone() is None: raise KeyError("schedule_not_found")
            c.execute(f"SELECT COALESCE(MAX(version_number),0)+1 FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); number = int(c.fetchone()[0])
            c.execute(f"INSERT INTO {self.t}.[requirement_schedule_versions](schedule_version_id,schedule_id,version_number,timezone,recurrence_json,run_policy,model,config_sha256,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,'draft',?,?)", vid, schedule_id, number, config.timezone, encoded, config.run_policy.value, config.model, digest, actor, now)
            self._enqueue_audit_event(c, self._audit_event("requirement_schedule.version_created", actor, schedule_id, schedule_version_id=vid, payload={"version_number": number}, created_at=now))
            connection.commit()
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
        return {"schedule_version_id": vid, "schedule_id": schedule_id, "version_number": number, "timezone": config.timezone, "recurrence": config.recurrence.as_dict(), "run_policy": config.run_policy.value, "model": config.model, "config_sha256": digest, "status": "draft", "created_by": actor, "created_at": now}

    def approve_version(self, *, schedule_id: str, version_number: int, actor: str, now_utc: datetime):
        connection = self._connect()
        try:
            c = connection.cursor(); c.execute(f"SELECT enabled,active_version_id,next_run_at FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); schedule = c.fetchone()
            if schedule is None: raise KeyError("schedule_not_found")
            c.execute(f"SELECT schedule_version_id,status,timezone,recurrence_json,run_policy,model,config_sha256 FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=? AND version_number=?", schedule_id, version_number); version = c.fetchone()
            if version is None: raise KeyError("schedule_version_not_found")
            vid, status, timezone_name, recurrence_json, run_policy, model, config_sha256 = version
            if status == "retired": raise ValueError("schedule_version_not_approved")
            if status == "approved" and schedule[1] == vid: connection.commit(); return {"schedule_version_id": vid, "status": "approved", "version_number": version_number}
            recurrence = self._validate_persisted_config(timezone_name, recurrence_json, run_policy, model, config_sha256).recurrence
            due = next_occurrence(recurrence, timezone_name, now_utc) if bool(schedule[0]) else None
            if schedule[1]: c.execute(f"UPDATE {self.t}.[requirement_schedule_versions] SET status='retired',retired_at=? WHERE schedule_version_id=? AND status='approved'", now_utc, schedule[1])
            c.execute(f"UPDATE {self.t}.[requirement_schedule_versions] SET status='approved',approved_by=?,approved_at=? WHERE schedule_version_id=? AND status='draft'", actor, now_utc, vid)
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET active_version_id=?,next_run_at=?,updated_by=?,updated_at=? WHERE schedule_id=?", vid, due, actor, now_utc, schedule_id)
            self._enqueue_audit_event(c, self._audit_event("requirement_schedule.version_approved", actor, schedule_id, schedule_version_id=vid, payload={"version_number": version_number}, created_at=now_utc))
            connection.commit()
            return {"schedule_version_id": vid, "status": "approved", "version_number": version_number}
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()

    def set_enabled(self, *, schedule_id: str, enabled: bool, actor: str, now_utc: datetime):
        connection = self._connect()
        try:
            c = connection.cursor(); c.execute(f"SELECT enabled,active_version_id,next_run_at FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); schedule = c.fetchone()
            if schedule is None: raise KeyError("schedule_not_found")
            if bool(schedule[0]) == bool(enabled):
                connection.commit()
                return {"schedule_id": schedule_id, "enabled": bool(enabled), "next_run_at": schedule[2]}
            due = None
            if enabled:
                if not schedule[1]: raise ValueError("schedule_version_not_approved")
                c.execute(f"SELECT status,timezone,recurrence_json,run_policy,model,config_sha256 FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_version_id=?", schedule[1]); version = c.fetchone()
                if version is None or version[0] != "approved": raise ValueError("schedule_version_not_approved")
                config = self._validate_persisted_config(version[1], version[2], version[3], version[4], version[5])
                due = next_occurrence(config.recurrence, config.timezone, now_utc)
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET enabled=?,next_run_at=?,updated_by=?,updated_at=? WHERE schedule_id=?", bool(enabled), due, actor, now_utc, schedule_id)
            action = "requirement_schedule.enabled" if enabled else "requirement_schedule.disabled"
            self._enqueue_audit_event(c, self._audit_event(action, actor, schedule_id, created_at=now_utc))
            connection.commit()
            return {"schedule_id": schedule_id, "enabled": bool(enabled), "next_run_at": due}
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()

    def list_pending_audit_events(self, limit: int) -> tuple[ScheduleAuditEvent, ...]:
        limit = max(1, min(int(limit), 100))
        rows = self._query(
            f"SELECT TOP (?) audit_event_id,action,actor,schedule_id,schedule_version_id,payload_json,created_at FROM {self.t}.[requirement_schedule_audit_outbox] WHERE delivered_at IS NULL ORDER BY created_at,audit_event_id",
            limit,
        )
        return tuple(ScheduleAuditEvent(row["audit_event_id"], row["action"], row["actor"], row["schedule_id"], row["schedule_version_id"], json.loads(row["payload_json"]), row["created_at"]) for row in rows)

    def mark_audit_delivered(self, event_id: str, at: datetime) -> bool:
        return self._update_audit_delivery(
            f"UPDATE {self.t}.[requirement_schedule_audit_outbox] SET delivery_attempts=delivery_attempts+1,last_delivery_attempt_at=?,last_delivery_error_code=NULL,delivered_at=? WHERE audit_event_id=? AND delivered_at IS NULL",
            at, at, event_id,
        )

    def mark_audit_failed(self, event_id: str, at: datetime) -> bool:
        return self._update_audit_delivery(
            f"UPDATE {self.t}.[requirement_schedule_audit_outbox] SET delivery_attempts=delivery_attempts+1,last_delivery_attempt_at=?,last_delivery_error_code='audit_sink_write_failed' WHERE audit_event_id=? AND delivered_at IS NULL",
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
            materialized = self._materialize_locked(c, schedule_id, version_id, policy, TriggerIdentity("scheduled", latest), now_utc, actor)
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

    def _materialize_locked(self, c, schedule_id: str, version_id: str, policy: str, trigger: TriggerIdentity, now_utc: datetime, actor: str) -> MaterializedRun:
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
            decision = evaluate_selection(policy, rv_id, int(rv_number), checkpoint, expires_at, now_utc)
            items.append({"run_item_id": _id("ri"), "requirement_id": requirement_id, "external_item_id": external_item_id, "requirement_version_id": rv_id, "requirement_version_number": int(rv_number), "source_order": int(source_order), "selection_status": "selected" if decision.selected else "skipped", "selection_reason": decision.reason, "expired_at_selection": decision.expired_at_selection})
        selected = sum(x["selection_status"] == "selected" for x in items); skipped = len(items) - selected
        phase1a_batch_id = f"reqrun-{run_id}"
        c.execute(f"INSERT INTO {self.t}.[requirement_batch_runs](batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,run_policy,phase1a_batch_id,state,selected_count,skipped_count,success_count,failure_count,deadline_elapsed_during_execution,created_by,created_at,materialized_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'handoff_pending',?,?,0,0,0,?,?,?,?)", run_id, schedule_id, version_id, trigger.trigger_type, trigger.trigger_request_id, trigger.scheduled_for, snapshot_id, policy, phase1a_batch_id, selected, skipped, actor, now_utc, now_utc, now_utc)
        for item in items:
            phase1a_task_id = item["external_item_id"] if item["selection_status"] == "selected" else None
            item["phase1a_task_id"] = phase1a_task_id
            c.execute(f"INSERT INTO {self.t}.[requirement_batch_run_items](run_item_id,batch_run_id,requirement_id,requirement_version_id,requirement_version_number,source_order,selection_status,selection_reason,phase1a_task_id,execution_state,expired_at_selection,expired_before_handoff,deadline_elapsed_during_execution,created_at,evaluated_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?)", item["run_item_id"], run_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], item["source_order"], item["selection_status"], item["selection_reason"], phase1a_task_id, "handoff_pending" if item["selection_status"] == "selected" else "not_selected", item["expired_at_selection"], now_utc, now_utc, now_utc)
            c.execute(f"MERGE {self.t}.[requirement_schedule_item_state] WITH (HOLDLOCK) AS t USING (SELECT ? schedule_id,? requirement_id) s ON t.schedule_id=s.schedule_id AND t.requirement_id=s.requirement_id WHEN MATCHED THEN UPDATE SET last_seen_requirement_version_id=?,last_seen_requirement_version_number=?,updated_at=? WHEN NOT MATCHED THEN INSERT(schedule_id,requirement_id,last_seen_requirement_version_id,last_seen_requirement_version_number,updated_at) VALUES (?,?,?,?,?);", schedule_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], now_utc, schedule_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], now_utc)
        return MaterializedRun({"batch_run_id": run_id, "phase1a_batch_id": phase1a_batch_id, "schedule_id": schedule_id, "schedule_version_id": version_id, "snapshot_id": snapshot_id, "state": "handoff_pending", "selected_count": selected, "skipped_count": skipped}, tuple(items))

    def materialize_run(self, *, schedule_id: str, trigger: TriggerIdentity, now_utc: datetime, actor: str) -> MaterializedRun:
        connection = self._connect()
        try:
            c = connection.cursor(); c.execute(f"SELECT active_version_id FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); schedule = c.fetchone()
            if not schedule or not schedule[0]: raise KeyError("schedule_not_found")
            c.execute(f"SELECT run_policy,status FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_version_id=?", schedule[0]); version = c.fetchone()
            if not version or version[1] != "approved": raise ValueError("schedule_version_not_approved")
            result = self._materialize_locked(c, schedule_id, schedule[0], version[0], trigger, now_utc, actor); connection.commit(); return result
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
