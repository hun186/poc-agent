from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from .connections import SqlRegistry
from .hashing import canonical_sha256
from .migrations import SCHEMA_VERSION, migration_v1, validate_schema_name
from .models import ImportProfileDocument, NormalizedCandidate, SourceMode, SourceType
from .source_adapters import validate_source_config


def _now() -> datetime: return datetime.now(timezone.utc)
def _id(prefix: str) -> str: return f"{prefix}_{uuid4().hex}"


class RequirementStore:
    """SQL Server-backed Phase 1B control-plane store."""
    def __init__(self, registry: SqlRegistry, connection_ref: str, schema: str = "sra_requirement"):
        self.registry, self.connection_ref, self.schema = registry, connection_ref, validate_schema_name(schema)

    def _connect(self): return self.registry.open_named_connection(self.connection_ref)

    def initialize(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            for statement in migration_v1(self.schema): cursor.execute(statement)
            table = f"[{self.schema}].[schema_version]"
            cursor.execute(f"SELECT version FROM {table}"); row = cursor.fetchone()
            if row is None: cursor.execute(f"INSERT INTO {table}(version) VALUES (?)", SCHEMA_VERSION)
            elif int(row[0]) != SCHEMA_VERSION: raise RuntimeError("unsupported requirement schema version")
            connection.commit()
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def _query(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        connection = self._connect()
        try: cursor = connection.cursor(); cursor.execute(sql, *params); return self._rows(cursor)
        finally: connection.close()

    def _execute(self, sql: str, *params: Any) -> None:
        connection = self._connect()
        try: connection.cursor().execute(sql, *params); connection.commit()
        except Exception: connection.rollback(); raise
        finally: connection.close()

    @property
    def t(self) -> str: return f"[{self.schema}]"

    def create_profile(self, name: str, description: str, actor: str, *, enabled: bool = False, profile_id: str | None = None) -> dict[str, Any]:
        pid, now = profile_id or _id("prof"), _now()
        self._execute(f"INSERT INTO {self.t}.[import_profiles] VALUES (?,?,?,?,NULL,?,?,?,?)", pid, name, description, enabled, actor, now, actor, now)
        return self.get_profile(pid)

    def list_profiles(self) -> list[dict[str, Any]]: return self._query(f"SELECT * FROM {self.t}.[import_profiles] ORDER BY created_at")
    def get_profile(self, profile_id: str) -> dict[str, Any]:
        rows = self._query(f"SELECT * FROM {self.t}.[import_profiles] WHERE profile_id=?", profile_id)
        if not rows: raise KeyError("profile_not_found")
        result = rows[0]; result["versions"] = self._query(f"SELECT profile_version_id,profile_id,version_number,format,source_mode,profile_sha256,status,created_by,created_at,approved_by,approved_at,retired_at FROM {self.t}.[import_profile_versions] WHERE profile_id=? ORDER BY version_number", profile_id)
        return result

    def patch_profile(self, profile_id: str, actor: str, **changes: Any) -> dict[str, Any]:
        allowed = {k: v for k, v in changes.items() if k in {"name", "description", "enabled"}}
        if not allowed: return self.get_profile(profile_id)
        assignments = ",".join(f"{key}=?" for key in allowed) + ",updated_by=?,updated_at=?"
        self._execute(f"UPDATE {self.t}.[import_profiles] SET {assignments} WHERE profile_id=?", *allowed.values(), actor, _now(), profile_id)
        return self.get_profile(profile_id)

    def create_profile_version(self, profile_id: str, document: dict[str, Any], actor: str) -> dict[str, Any]:
        profile = ImportProfileDocument.model_validate(document); serialized = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")); digest = canonical_sha256(profile.model_dump(mode="json"))
        connection = self._connect()
        try:
            cursor = connection.cursor(); cursor.execute(f"SELECT COALESCE(MAX(version_number),0)+1 FROM {self.t}.[import_profile_versions] WITH (UPDLOCK,HOLDLOCK) WHERE profile_id=?", profile_id); number = int(cursor.fetchone()[0]); vid = _id("pv")
            cursor.execute(f"INSERT INTO {self.t}.[import_profile_versions] VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)", vid, profile_id, number, profile.format, profile.source_mode.value, serialized, digest, "draft", actor, _now()); connection.commit()
        except Exception: connection.rollback(); raise
        finally: connection.close()
        return self.get_profile_version(vid)

    def get_profile_version(self, profile_version_id: str) -> dict[str, Any]:
        rows = self._query(f"SELECT * FROM {self.t}.[import_profile_versions] WHERE profile_version_id=?", profile_version_id)
        if not rows: raise KeyError("profile_version_not_found")
        result = rows[0]; result["profile"] = ImportProfileDocument.model_validate_json(result.pop("profile_json")); return result

    def approve_profile_version(self, profile_id: str, version_number: int, actor: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            cursor = connection.cursor(); cursor.execute(f"SELECT profile_version_id FROM {self.t}.[import_profile_versions] WITH (UPDLOCK,HOLDLOCK) WHERE profile_id=? AND version_number=?", profile_id, version_number); row = cursor.fetchone()
            if row is None: raise KeyError("profile_version_not_found")
            vid = row[0]; now = _now(); cursor.execute(f"UPDATE {self.t}.[import_profile_versions] SET status='approved',approved_by=?,approved_at=? WHERE profile_version_id=? AND status IN ('draft','approved')", actor, now, vid); cursor.execute(f"UPDATE {self.t}.[import_profiles] SET active_version_id=?,updated_by=?,updated_at=? WHERE profile_id=?", vid, actor, now, profile_id); connection.commit()
        except Exception: connection.rollback(); raise
        finally: connection.close()
        return self.get_profile_version(vid)

    def get_active_profile_version(self, profile_id: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        if not profile.get("enabled") or not profile.get("active_version_id"): raise ValueError("profile_invalid")
        version = self.get_profile_version(profile["active_version_id"])
        if version["status"] != "approved": raise ValueError("profile_invalid")
        return version

    def create_source(self, name: str, source_type: str, source_mode: str, source_config: dict[str, Any], import_profile_id: str, actor: str, *, enabled: bool = False, source_id: str | None = None) -> dict[str, Any]:
        kind, mode = SourceType(source_type), SourceMode(source_mode); config = validate_source_config(kind, source_config); sid, now = source_id or _id("src"), _now()
        self._execute(f"INSERT INTO {self.t}.[requirement_sources] VALUES (?,?,?,?,?,?,?,?,?,?,?)", sid, name, kind.value, mode.value, json.dumps(config), import_profile_id, enabled, actor, now, actor, now)
        return self.get_source(sid)

    def list_sources(self) -> list[dict[str, Any]]: return [self._source(row) for row in self._query(f"SELECT * FROM {self.t}.[requirement_sources] ORDER BY created_at")]
    def _source(self, row: dict[str, Any]) -> dict[str, Any]: row["source_config"] = json.loads(row.pop("source_config_json")); return row
    def get_source(self, source_id: str) -> dict[str, Any]:
        rows = self._query(f"SELECT * FROM {self.t}.[requirement_sources] WHERE source_id=?", source_id)
        if not rows: raise KeyError("source_not_found")
        return self._source(rows[0])
    def patch_source(self, source_id: str, actor: str, **changes: Any) -> dict[str, Any]:
        current = self.get_source(source_id); allowed = {k: v for k, v in changes.items() if k in {"name", "source_mode", "enabled", "import_profile_id"}}
        if "source_config" in changes: allowed["source_config_json"] = json.dumps(validate_source_config(current["source_type"], changes["source_config"]))
        assignments = ",".join(f"{key}=?" for key in allowed) + ",updated_by=?,updated_at=?"; self._execute(f"UPDATE {self.t}.[requirement_sources] SET {assignments} WHERE source_id=?", *allowed.values(), actor, _now(), source_id); return self.get_source(source_id)

    def current_versions(self, source_id: str) -> dict[str, dict[str, Any]]:
        rows = self._query(f"SELECT r.external_item_id,v.* FROM {self.t}.[requirements] r JOIN {self.t}.[requirement_versions] v ON v.requirement_id=r.requirement_id WHERE r.source_id=? AND v.version_number=(SELECT MAX(v2.version_number) FROM {self.t}.[requirement_versions] v2 WHERE v2.requirement_id=r.requirement_id)", source_id)
        return {row["external_item_id"]: row for row in rows}

    # Commit deliberately re-runs comparison while holding update locks.
    def commit_candidate(self, source: dict[str, Any], version: dict[str, Any], acquired: Any, candidate: NormalizedCandidate, actor: str) -> dict[str, Any]:
        if candidate.has_errors: return self.record_failed_import(source, version, acquired, candidate, actor)
        connection = self._connect(); now = _now(); run_id, snapshot_id = _id("run"), _id("snap")
        try:
            c = connection.cursor(); c.execute(f"SELECT source_id FROM {self.t}.[requirement_sources] WITH (UPDLOCK,HOLDLOCK) WHERE source_id=? AND enabled=1", source["source_id"])
            if c.fetchone() is None: raise ValueError("source_disabled")
            c.execute(f"SELECT requirement_set_id,active_snapshot_id FROM {self.t}.[requirement_sets] WITH (UPDLOCK,HOLDLOCK) WHERE source_id=?", source["source_id"]); setrow = c.fetchone()
            set_id, prior_snapshot = (setrow[0], setrow[1]) if setrow else (_id("set"), None)
            if not setrow: c.execute(f"INSERT INTO {self.t}.[requirement_sets] VALUES (?,?,?,NULL,?)", set_id, source["source_id"], source["name"], now)
            memberships: list[tuple[str, str, int]] = []
            for order, row in enumerate(candidate.rows, 1):
                c.execute(f"SELECT requirement_id FROM {self.t}.[requirements] WITH (UPDLOCK,HOLDLOCK) WHERE source_id=? AND external_item_id=?", source["source_id"], row.external_item_id); req = c.fetchone(); rid = req[0] if req else _id("req")
                if not req: c.execute(f"INSERT INTO {self.t}.[requirements] VALUES (?,?,?,?)", rid, source["source_id"], row.external_item_id, now)
                c.execute(f"SELECT TOP 1 requirement_version_id,version_number,source_updated_at,source_payload_hash,source_row_hash FROM {self.t}.[requirement_versions] WHERE requirement_id=? ORDER BY version_number DESC", rid); old = c.fetchone()
                if old and row.source_updated_at < old[2]: raise ValueError("stale_source_version")
                if old and row.source_updated_at == old[2] and row.source_payload_hash != old[3]: raise ValueError("source_version_anomaly")
                if old and row.source_payload_hash == old[3]: rvid = old[0]
                else:
                    rvid, number = _id("rv"), (int(old[1]) + 1 if old else 1)
                    c.execute(f"INSERT INTO {self.t}.[requirement_versions] VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rvid, rid, number, row.title, row.prompt_content, row.source_updated_at, row.expires_at, row.source_created_by, row.source_updated_by, row.source_created_at, row.source_row_hash, row.source_payload_hash, row.execution_content_hash, json.dumps(row.source_raw, default=str, ensure_ascii=False), now)
                memberships.append((rid, rvid, order))
            if source["source_mode"] == SourceMode.UPSERT_DELTA.value and prior_snapshot:
                c.execute(f"SELECT requirement_id,requirement_version_id,source_order FROM {self.t}.[requirement_snapshot_items] WHERE snapshot_id=?", prior_snapshot)
                present = {item[0] for item in memberships}; memberships.extend((r[0], r[1], r[2]) for r in c.fetchall() if r[0] not in present)
            c.execute(f"INSERT INTO {self.t}.[import_runs] VALUES (?,?,?,?,?,'staged',?,?,?,?,?,'user',?,NULL)", run_id, source["source_id"], version["profile_version_id"], acquired.source_uri_display, acquired.source_sha256, len(candidate.rows), len(candidate.rows), 0, now, now, actor)
            for row in candidate.rows: c.execute(f"INSERT INTO {self.t}.[import_run_rows] VALUES (?,?,?,?,?,?,?)", run_id, row.source_row_number, row.external_item_id, "accepted", row.source_row_hash, None, None)
            c.execute(f"INSERT INTO {self.t}.[requirement_set_snapshots] VALUES (?,?,?,?,?,?,?)", snapshot_id, set_id, run_id, acquired.source_sha256, version["profile_version_id"], now, now)
            for rid, rvid, order in memberships: c.execute(f"INSERT INTO {self.t}.[requirement_snapshot_items] VALUES (?,?,?,?)", snapshot_id, rid, rvid, order)
            c.execute(f"UPDATE {self.t}.[requirement_sets] SET active_snapshot_id=? WHERE requirement_set_id=?", snapshot_id, set_id); c.execute(f"UPDATE {self.t}.[import_runs] SET status='committed',completed_at=? WHERE import_run_id=?", now, run_id); connection.commit()
        except Exception:
            connection.rollback(); raise
        finally: connection.close()
        return {"import_run_id": run_id, "snapshot_id": snapshot_id, "status": "committed", "accepted_count": len(candidate.rows), "rejected_count": 0}

    def record_failed_import(self, source: dict[str, Any], version: dict[str, Any], acquired: Any, candidate: NormalizedCandidate, actor: str) -> dict[str, Any]:
        run_id, now = _id("run"), _now(); self._execute(f"INSERT INTO {self.t}.[import_runs] VALUES (?,?,?,?,?,'failed',?,?,?,?,?,'user',?,?)", run_id, source["source_id"], version["profile_version_id"], acquired.source_uri_display, acquired.source_sha256, len(candidate.rows) + len(candidate.diagnostics), len(candidate.rows), len(candidate.diagnostics), now, now, actor, candidate.diagnostics[0].code if candidate.diagnostics else "import_failed")
        return {"import_run_id": run_id, "snapshot_id": None, "status": "failed", "accepted_count": len(candidate.rows), "rejected_count": len(candidate.diagnostics)}

    def get_import_run(self, run_id: str) -> dict[str, Any]:
        rows = self._query(f"SELECT * FROM {self.t}.[import_runs] WHERE import_run_id=?", run_id)
        if not rows: raise KeyError("import_run_not_found")
        rows[0]["rows"] = self._query(f"SELECT * FROM {self.t}.[import_run_rows] WHERE import_run_id=? ORDER BY source_row_number", run_id); return rows[0]
    def list_requirement_sets(self): return self._query(f"SELECT * FROM {self.t}.[requirement_sets] ORDER BY created_at")
    def list_snapshots(self, set_id: str): return self._query(f"SELECT * FROM {self.t}.[requirement_set_snapshots] WHERE requirement_set_id=? ORDER BY created_at", set_id)
    def get_snapshot(self, snapshot_id: str):
        rows = self._query(f"SELECT * FROM {self.t}.[requirement_set_snapshots] WHERE snapshot_id=?", snapshot_id)
        if not rows: raise KeyError("snapshot_not_found")
        return rows[0]
    def list_snapshot_items(self, snapshot_id: str): return self._query(f"SELECT i.*,r.external_item_id,v.title,v.prompt_content,v.source_updated_at,v.expires_at,v.source_created_by,v.source_updated_by,v.source_created_at FROM {self.t}.[requirement_snapshot_items] i JOIN {self.t}.[requirements] r ON r.requirement_id=i.requirement_id JOIN {self.t}.[requirement_versions] v ON v.requirement_version_id=i.requirement_version_id WHERE i.snapshot_id=? ORDER BY i.source_order", snapshot_id)
