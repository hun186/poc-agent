from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import ImportProfileDocument, RowDiagnostic, SourceMode
from .profile import normalize_rows
from .source_adapters import acquire_source


class RequirementImportService:
    def __init__(self, store: Any, registry: Any | None = None, allowed_roots: str | None = None):
        self.store, self.registry, self.allowed_roots = store, registry, allowed_roots

    def _prepare(self, source_id: str, *, profile_version_id: str | None, upload_bytes: bytes | None, upload_filename: str | None, commit: bool) -> tuple[Any, ...]:
        source = self.store.get_source(source_id)
        version = self.store.get_active_profile_version(source["import_profile_id"]) if commit or profile_version_id is None else self.store.get_profile_version(profile_version_id)
        if version["profile_id"] != source["import_profile_id"]: raise ValueError("profile_invalid")
        profile: ImportProfileDocument = version["profile"]
        if profile.source_mode.value != source["source_mode"]: raise ValueError("profile_invalid")
        acquired = acquire_source(source, profile, upload_bytes=upload_bytes, upload_filename=upload_filename, registry=self.registry, allowed_roots=self.allowed_roots)
        candidate = normalize_rows(acquired.rows, profile, acquired.source_row_numbers)
        classifications: list[dict[str, Any]] = []
        current = self.store.current_versions(source_id)
        for row in candidate.rows:
            old = current.get(row.external_item_id)
            if old is None: classification = "new"
            elif row.source_updated_at < old["source_updated_at"]:
                classification = "stale"; candidate.diagnostics.append(RowDiagnostic(source_row_number=row.source_row_number, external_item_id=row.external_item_id, code="stale_source_version", message="Source timestamp is older"))
            elif row.source_updated_at == old["source_updated_at"] and row.source_payload_hash != old["source_payload_hash"]:
                classification = "anomaly"; candidate.diagnostics.append(RowDiagnostic(source_row_number=row.source_row_number, external_item_id=row.external_item_id, code="source_version_anomaly", message="Payload changed without source version change"))
            elif row.source_payload_hash == old["source_payload_hash"]: classification = "unchanged"
            elif row.execution_content_hash == old["execution_content_hash"]: classification = "provenance_only"
            else: classification = "changed"
            classifications.append({"external_item_id": row.external_item_id, "classification": classification})
        if source["source_mode"] == SourceMode.AUTHORITATIVE_SNAPSHOT.value:
            present = {row.external_item_id for row in candidate.rows}
            classifications.extend({"external_item_id": key, "classification": "removal_candidate"} for key in current if key not in present)
        return source, version, acquired, candidate, classifications

    def preview(self, source_id: str, *, profile_version_id: str | None = None, upload_bytes: bytes | None = None, upload_filename: str | None = None) -> dict[str, Any]:
        source, version, acquired, candidate, classifications = self._prepare(source_id, profile_version_id=profile_version_id, upload_bytes=upload_bytes, upload_filename=upload_filename, commit=False)
        now = datetime.now(timezone.utc)
        counts: dict[str, int] = {}
        for item in classifications: counts[item["classification"]] = counts.get(item["classification"], 0) + 1
        return {"source_id": source_id, "profile_version_id": version["profile_version_id"], "source_sha256": acquired.source_sha256, "row_count": len(acquired.rows), "accepted_count": len(candidate.rows), "rejected_count": len(candidate.diagnostics), "expired_count": sum(row.expires_at is not None and row.expires_at <= now for row in candidate.rows), "has_errors": candidate.has_errors, "counts": counts, "classifications": classifications, "diagnostics": [item.model_dump(mode="json") for item in candidate.diagnostics]}

    def commit(
        self,
        source_id: str,
        *,
        actor: str,
        upload_bytes: bytes | None = None,
        upload_filename: str | None = None,
        import_run_id: str | None = None,
        snapshot_id: str | None = None,
        expected_base_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        if import_run_id is not None:
            recovered = self.store.recover_preallocated_import_result(
                source_id, import_run_id, snapshot_id
            )
            if recovered is not None:
                return recovered
        source, version, acquired, candidate, _ = self._prepare(
            source_id,
            profile_version_id=None,
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            commit=True,
        )
        if (
            import_run_id is None
            and snapshot_id is None
            and expected_base_snapshot_id is None
        ):
            return self.store.commit_candidate(source, version, acquired, candidate, actor)
        return self.store.commit_candidate(
            source,
            version,
            acquired,
            candidate,
            actor,
            import_run_id=import_run_id,
            snapshot_id=snapshot_id,
            expected_base_snapshot_id=expected_base_snapshot_id,
        )
