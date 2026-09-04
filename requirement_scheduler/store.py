from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from .migrations import (
    ForeignKey, KeyConstraint, SCHEMA_VERSION, bootstrap_schema_statements,
    migration_0_to_1_statements, validate_schema_name, validation_queries,
)
from .models import MaterializedRun, RecurrenceSpec, ScheduleVersionCreate, TriggerIdentity
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
    }: return exc
    return RuntimeError("persistence_error")


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
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def initialize(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            for sql in bootstrap_schema_statements(self.schema): cursor.execute(sql)
            cursor.execute(f"SELECT version FROM {self.t}.[schema_version]"); row = cursor.fetchone()
            version = 0 if row is None else int(row[0])
            if version == 0:
                for sql in migration_0_to_1_statements(self.schema, self.requirement_schema): cursor.execute(sql)
            elif version != SCHEMA_VERSION: raise RuntimeError("unsupported schedule schema version")
            for name, sql, params, expected in validation_queries(self.schema, self.requirement_schema):
                cursor.execute(sql, *params); rows = tuple(cursor.fetchall())
                if isinstance(expected, KeyConstraint):
                    actual = tuple((r[4], int(r[5])) for r in rows)
                    valid = all(r[0] == self.schema and r[1] == expected.table and r[2] == expected.name and r[3] == expected.kind for r in rows) and actual == tuple((c, i) for i, c in enumerate(expected.columns, 1))
                elif isinstance(expected, ForeignKey):
                    valid = tuple((r[3], r[4], r[5], r[6], int(r[7])) for r in rows) == tuple((c, expected.referenced_schema, expected.referenced_table, rc, i) for i, (c, rc) in enumerate(zip(expected.columns, expected.referenced_columns), 1)) and all(r[0] == self.schema and r[1] == expected.table and r[2] == expected.name for r in rows)
                else:
                    valid = tuple(r[0] for r in rows) == tuple(expected)
                if not valid: raise RuntimeError("malformed schedule schema version 1")
            if version == 0:
                if row is None: cursor.execute(f"INSERT INTO {self.t}.[schema_version](version) VALUES (?)", SCHEMA_VERSION)
                else: cursor.execute(f"UPDATE {self.t}.[schema_version] SET version=? WHERE version=0", SCHEMA_VERSION)
            connection.commit()
        except Exception as exc:
            connection.rollback()
            if str(exc) in {"unsupported schedule schema version", "malformed schedule schema version 1"}: raise
            raise _safe_error(exc) from exc
        finally: connection.close()

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
            connection.commit()
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
        return {"schedule_id": sid, "name": name.strip(), "requirement_set_id": requirement_set_id, "enabled": False, "active_version_id": None, "next_run_at": None, "created_by": actor, "created_at": now, "updated_by": actor, "updated_at": now}

    def _query(self, sql: str, *params) -> list[dict[str, Any]]:
        connection = self._connect()
        try: c = connection.cursor(); c.execute(sql, *params); return self._rows(c)
        except Exception as exc: raise _safe_error(exc) from exc
        finally: connection.close()

    def list_schedules(self): return self._query(f"SELECT * FROM {self.t}.[requirement_schedules] ORDER BY created_at")
    def get_schedule(self, schedule_id: str):
        rows = self._query(f"SELECT * FROM {self.t}.[requirement_schedules] WHERE schedule_id=?", schedule_id)
        if not rows: raise KeyError("schedule_not_found")
        return rows[0]

    def rename_schedule(self, schedule_id: str, name: str, actor: str):
        if not name.strip(): raise ValueError("schedule_name_invalid")
        connection = self._connect(); now = _now()
        try:
            c = connection.cursor(); c.execute(f"UPDATE {self.t}.[requirement_schedules] SET name=?,updated_by=?,updated_at=? WHERE schedule_id=? AND enabled=0", name.strip(), actor, now, schedule_id)
            if getattr(c, "rowcount", 1) != 1: raise ValueError("schedule_enabled")
            connection.commit()
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
        return self.get_schedule(schedule_id)

    @staticmethod
    def canonical_config(config: ScheduleVersionCreate) -> tuple[str, str]:
        document = {"schema_version": 1, "timezone": config.timezone, "recurrence": config.recurrence.as_dict(), "run_policy": config.run_policy.value, "model": config.model}
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return encoded, hashlib.sha256(encoded.encode()).hexdigest()

    def create_version(self, *, schedule_id: str, config: ScheduleVersionCreate, actor: str) -> dict[str, Any]:
        encoded, digest = self.canonical_config(config); connection = self._connect(); now = _now(); vid = _id("sv")
        try:
            c = connection.cursor(); c.execute(f"SELECT schedule_id FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id)
            if c.fetchone() is None: raise KeyError("schedule_not_found")
            c.execute(f"SELECT COALESCE(MAX(version_number),0)+1 FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); number = int(c.fetchone()[0])
            c.execute(f"INSERT INTO {self.t}.[requirement_schedule_versions](schedule_version_id,schedule_id,version_number,timezone,recurrence_json,run_policy,model,config_sha256,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,'draft',?,?)", vid, schedule_id, number, config.timezone, encoded, config.run_policy.value, config.model, digest, actor, now); connection.commit()
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()
        return {"schedule_version_id": vid, "schedule_id": schedule_id, "version_number": number, "timezone": config.timezone, "recurrence": config.recurrence.as_dict(), "run_policy": config.run_policy.value, "model": config.model, "config_sha256": digest, "status": "draft", "created_by": actor, "created_at": now}

    def approve_version(self, *, schedule_id: str, version_number: int, actor: str, now_utc: datetime):
        connection = self._connect()
        try:
            c = connection.cursor(); c.execute(f"SELECT enabled,active_version_id FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); schedule = c.fetchone()
            if schedule is None: raise KeyError("schedule_not_found")
            c.execute(f"SELECT schedule_version_id,status,timezone,recurrence_json FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=? AND version_number=?", schedule_id, version_number); version = c.fetchone()
            if version is None: raise KeyError("schedule_version_not_found")
            vid, status, timezone_name, recurrence_json = version
            if status == "retired": raise ValueError("schedule_version_not_approved")
            if status == "approved" and schedule[1] == vid: connection.commit(); return {"schedule_version_id": vid, "status": "approved", "version_number": version_number}
            recurrence_document = json.loads(recurrence_json)
            recurrence = RecurrenceSpec.validate(recurrence_document.get("recurrence", recurrence_document))
            due = next_occurrence(recurrence, timezone_name, now_utc) if bool(schedule[0]) else None
            if schedule[1]: c.execute(f"UPDATE {self.t}.[requirement_schedule_versions] SET status='retired',retired_at=? WHERE schedule_version_id=? AND status='approved'", now_utc, schedule[1])
            c.execute(f"UPDATE {self.t}.[requirement_schedule_versions] SET status='approved',approved_by=?,approved_at=? WHERE schedule_version_id=? AND status='draft'", actor, now_utc, vid)
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET active_version_id=?,next_run_at=?,updated_by=?,updated_at=? WHERE schedule_id=?", vid, due, actor, now_utc, schedule_id); connection.commit()
            return {"schedule_version_id": vid, "status": "approved", "version_number": version_number}
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()

    def set_enabled(self, *, schedule_id: str, enabled: bool, actor: str, now_utc: datetime):
        connection = self._connect()
        try:
            c = connection.cursor(); c.execute(f"SELECT enabled,active_version_id FROM {self.t}.[requirement_schedules] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=?", schedule_id); schedule = c.fetchone()
            if schedule is None: raise KeyError("schedule_not_found")
            due = None
            if enabled:
                if not schedule[1]: raise ValueError("schedule_version_not_approved")
                c.execute(f"SELECT status,timezone,recurrence_json FROM {self.t}.[requirement_schedule_versions] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_version_id=?", schedule[1]); version = c.fetchone()
                if version is None or version[0] != "approved": raise ValueError("schedule_version_not_approved")
                document = json.loads(version[2]); due = next_occurrence(RecurrenceSpec.validate(document.get("recurrence", document)), version[1], now_utc)
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET enabled=?,next_run_at=?,updated_by=?,updated_at=? WHERE schedule_id=?", bool(enabled), due, actor, now_utc, schedule_id); connection.commit()
            return {"schedule_id": schedule_id, "enabled": bool(enabled), "next_run_at": due}
        except Exception as exc: connection.rollback(); raise _safe_error(exc) from exc
        finally: connection.close()

    def claim_due(self, *, now_utc: datetime, actor: str):
        """Claim at most one latest due occurrence and advance it atomically."""
        connection = self._connect()
        try:
            c = connection.cursor()
            c.execute(f"SELECT TOP 1 s.schedule_id,s.active_version_id,s.next_run_at,v.timezone,v.recurrence_json,v.run_policy FROM {self.t}.[requirement_schedules] s WITH (UPDLOCK,HOLDLOCK) JOIN {self.t}.[requirement_schedule_versions] v WITH (UPDLOCK,HOLDLOCK) ON v.schedule_version_id=s.active_version_id WHERE s.enabled=1 AND s.next_run_at<=? AND v.status='approved' ORDER BY s.next_run_at,s.schedule_id", now_utc)
            row = c.fetchone()
            if row is None: connection.commit(); return None
            schedule_id, version_id, persisted_due, timezone_name, recurrence_json, policy = row
            document = json.loads(recurrence_json); spec = RecurrenceSpec.validate(document.get("recurrence", document))
            latest, following = coalesce_latest(spec, timezone_name, persisted_due, now_utc)
            materialized = self._materialize_locked(c, schedule_id, version_id, policy, TriggerIdentity("scheduled", latest), now_utc, actor)
            run_id = materialized.run["batch_run_id"]
            c.execute(f"UPDATE {self.t}.[requirement_schedules] SET next_run_at=?,updated_by=?,updated_at=? WHERE schedule_id=? AND active_version_id=?", following, actor, now_utc, schedule_id, version_id); connection.commit()
            return {"batch_run_id": run_id, "schedule_id": schedule_id, "schedule_version_id": version_id, "scheduled_for": latest, "next_run_at": following}
        except Exception as exc:
            connection.rollback()
            # A filtered-unique race is reconciled by a fresh read on the next claim.
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
            c.execute(f"INSERT INTO {self.t}.[requirement_batch_runs](batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,run_policy,phase1a_batch_id,state,selected_count,skipped_count,success_count,failure_count,error_code,error_message,deadline_elapsed_during_execution,created_by,created_at,materialized_at,updated_at) VALUES (?,?,?,?,?,?,NULL,?,?,'blocked_no_snapshot',0,0,0,0,'no_active_snapshot','No active Requirement snapshot',0,?,?,?,?)", run_id, schedule_id, version_id, trigger.trigger_type, trigger.trigger_request_id, trigger.scheduled_for, policy, f"phase1c-{run_id}", actor, now_utc, now_utc, now_utc)
            return MaterializedRun({"batch_run_id": run_id, "schedule_id": schedule_id, "snapshot_id": None, "state": "blocked_no_snapshot"}, ())
        c.execute(f"SELECT i.requirement_id,i.requirement_version_id,v.version_number,i.source_order,v.expires_at FROM [{self.requirement_schema}].[requirement_snapshot_items] i WITH (HOLDLOCK) JOIN [{self.requirement_schema}].[requirement_versions] v WITH (HOLDLOCK) ON v.requirement_version_id=i.requirement_version_id WHERE i.snapshot_id=? ORDER BY i.source_order", snapshot_id); source_items = tuple(c.fetchall())
        items = []
        for requirement_id, rv_id, rv_number, source_order, expires_at in source_items:
            c.execute(f"SELECT last_seen_requirement_version_id,last_seen_requirement_version_number,last_successful_requirement_version_id,last_successful_requirement_version_number FROM {self.t}.[requirement_schedule_item_state] WITH (UPDLOCK,HOLDLOCK) WHERE schedule_id=? AND requirement_id=?", schedule_id, requirement_id); cp = c.fetchone()
            checkpoint = Checkpoint(*(cp or (None, None, None, None)))
            decision = evaluate_selection(policy, rv_id, int(rv_number), checkpoint, expires_at, now_utc)
            items.append({"run_item_id": _id("ri"), "requirement_id": requirement_id, "requirement_version_id": rv_id, "requirement_version_number": int(rv_number), "source_order": int(source_order), "selection_status": "selected" if decision.selected else "skipped", "selection_reason": decision.reason, "expired_at_selection": decision.expired_at_selection})
        selected = sum(x["selection_status"] == "selected" for x in items); skipped = len(items) - selected
        c.execute(f"INSERT INTO {self.t}.[requirement_batch_runs](batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,run_policy,phase1a_batch_id,state,selected_count,skipped_count,success_count,failure_count,deadline_elapsed_during_execution,created_by,created_at,materialized_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'handoff_pending',?,?,0,0,0,?,?,?,?)", run_id, schedule_id, version_id, trigger.trigger_type, trigger.trigger_request_id, trigger.scheduled_for, snapshot_id, policy, f"phase1c-{run_id}", selected, skipped, actor, now_utc, now_utc, now_utc)
        for item in items:
            c.execute(f"INSERT INTO {self.t}.[requirement_batch_run_items](run_item_id,batch_run_id,requirement_id,requirement_version_id,requirement_version_number,source_order,selection_status,selection_reason,phase1a_task_id,execution_state,expired_at_selection,expired_before_handoff,deadline_elapsed_during_execution,created_at,evaluated_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?)", item["run_item_id"], run_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], item["source_order"], item["selection_status"], item["selection_reason"], item["requirement_id"] if item["selection_status"] == "selected" else None, "handoff_pending" if item["selection_status"] == "selected" else "not_selected", item["expired_at_selection"], now_utc, now_utc, now_utc)
            c.execute(f"MERGE {self.t}.[requirement_schedule_item_state] WITH (HOLDLOCK) AS t USING (SELECT ? schedule_id,? requirement_id) s ON t.schedule_id=s.schedule_id AND t.requirement_id=s.requirement_id WHEN MATCHED THEN UPDATE SET last_seen_requirement_version_id=?,last_seen_requirement_version_number=?,updated_at=? WHEN NOT MATCHED THEN INSERT(schedule_id,requirement_id,last_seen_requirement_version_id,last_seen_requirement_version_number,updated_at) VALUES (?,?,?,?,?);", schedule_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], now_utc, schedule_id, item["requirement_id"], item["requirement_version_id"], item["requirement_version_number"], now_utc)
        return MaterializedRun({"batch_run_id": run_id, "schedule_id": schedule_id, "schedule_version_id": version_id, "snapshot_id": snapshot_id, "state": "handoff_pending", "selected_count": selected, "skipped_count": skipped}, tuple(items))

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
