#!/usr/bin/env python3
"""One-command deployment-host Requirement automatic-schedule E2E harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from openpyxl import load_workbook

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from config.bootstrap import bootstrap_env
from data_ingestion.requirements.hashing import canonical_sha256
from data_ingestion.requirements.models import ImportProfileDocument
from operator_e2e.requirement_e2e_support import (
    CANONICAL_SOURCE_SHA256, E2EConfig, ExitCode, HarnessFailure, SingleRunLock, StageStatus, atomic_write_json,
    atomic_write_text, bounded_log_tail, classify_new_batch, has_usable_requirement_process_configuration,
    load_e2e_environment, redact, result_document, terminal_failure,
    validate_live_platform, validate_next_run, validate_preview, validate_remote_items,
    validate_terminal,
)
from operator_e2e.requirement_e2e_evidence import LocalDeploymentEvidenceProvider, RemoteDeploymentEvidenceProvider
from shared.runtime_provenance import (
    PROVENANCE_NAME, load_provenance, provenance_fingerprint, verify_package_files,
)

PROFILE_PATH = SCRIPT_DIR / "requirement_e2e_profile_v1.json"
DEFAULT_EXCEL = SCRIPT_DIR / "input" / "requirement_e2e_3items.xlsx"
TRANSIENT = {429, 502, 503, 504}


class Api:
    def __init__(self, config: E2EConfig): self.config, self.token = config, config.token
    @property
    def headers(self): return {"Authorization": f"Bearer {self.token}"} if self.token else {}
    def request(self, method: str, path: str, *, read_retry: bool = False, timeout: int = 30, **kwargs):
        response = self.request_raw(method, path, read_retry=read_retry, timeout=timeout, **kwargs)
        return response.json() if response.content else {}
    def request_raw(self, method: str, path: str, *, read_retry: bool = False, timeout: int = 30, **kwargs):
        if method.upper() == "POST" and path.rstrip("/").endswith("/runs"):
            raise AssertionError("manual run forbidden")
        deadline = time.monotonic() + timeout
        while True:
            try:
                response = requests.request(method, self.config.base_url + path, headers=self.headers, timeout=(5, timeout), **kwargs)
                if read_retry and response.status_code in TRANSIENT and time.monotonic() < deadline: time.sleep(1); continue
                if response.status_code >= 400:
                    category = "authentication_failed" if response.status_code == 401 else "authorization_failed" if response.status_code == 403 else "api_request_failed"
                    if path.startswith("/v1/operator-e2e/"):
                        try: code = response.json().get("detail", {}).get("code")
                        except (AttributeError, ValueError): code = None
                        if code in {"artifact_missing", "artifact_invalid", "artifact_metadata_missing", "artifact_sha256_mismatch", "artifact_root_fingerprint_mismatch",
                                    "active_runtime_source_mismatch", "unexpected_active_runtime_module",
                                    "unexpected_runtime_input",
                                    "runtime_module_shadowing", "release_provenance_invalid",
                                    "release_provenance_missing"}:
                            category = code
                    raise HarnessFailure(category)
                return response
            except (requests.Timeout, requests.ConnectionError):
                if read_retry and time.monotonic() < deadline: time.sleep(1); continue
                raise
    def get(self, path: str, **kwargs): return self.request("GET", path, read_retry=True, **kwargs)
    def post(self, path: str, **kwargs): return self.request("POST", path, **kwargs)
    def patch(self, path: str, **kwargs): return self.request("PATCH", path, **kwargs)


class Harness:
    PROGRESS_HEARTBEAT_SECONDS = 15

    def __init__(self, config: E2EConfig, excel: Path, run_id: str, result: dict[str, Any]):
        self.config, self.excel, self.run_id, self.result = config, excel, run_id, result
        self.api = Api(config); self.enabled_schedule_id: str | None = None
        self.output = config.output_dir / run_id; self.known_secrets = [x for x in (config.token, config.password) if x]
        self.evidence_provider = None

    def log(self, event: str, **fields):
        """Emit one redacted, deterministic operator progress record."""
        safe = redact(fields, self.known_secrets)
        parts = [f"[E2E {datetime.now(timezone.utc):%H:%M:%S}]", event]
        for key in sorted(safe):
            value = safe[key]
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
            parts.append(f"{key}={value}")
        print(" ".join(parts), flush=True)

    def pass_stage(self, name: str, **evidence):
        stage = next(item for item in self.result["stages"] if item["name"] == name)
        safe_evidence = redact(evidence, self.known_secrets)
        stage.update(status=StageStatus.PASS, evidence=safe_evidence)
        self.log(f"PASS {name}", **safe_evidence)

    @staticmethod
    def _progress_snapshot(batch):
        items = [
            {key: item.get(key) for key in (
                "run_item_id", "requirement_id", "remote_job_id",
                "remote_job_state", "execution_state",
            )}
            for item in batch.get("items", []) if item.get("selection_status") == "selected"
        ]
        items.sort(key=lambda item: str(item.get("run_item_id") or ""))
        completed = sum(
            item["remote_job_state"] == "completed" and item["execution_state"] == "completed"
            for item in items
        )
        summary = {
            "batch_state": batch.get("state"), "success": batch.get("success_count"),
            "failure": batch.get("failure_count"), "completed": f"{completed}/{len(items)}",
        }
        signature = (tuple(summary.values()), tuple(tuple(item.values()) for item in items))
        return summary, items, signature

    def _log_progress_snapshot(self, event: str, batch, **fields):
        summary, items, signature = self._progress_snapshot(batch)
        self.log(event, **summary, **fields)
        for item in items: self.log("ITEM", **item)
        return signature

    def fail(self, category: str, stage: str, exit_code=ExitCode.FUNCTIONAL):
        raise HarnessFailure(category, stage=stage, exit_code=exit_code)

    def authenticate(self):
        if self.api.token: return
        try:
            value = self.api.post("/v1/auth/login", json={"username": self.config.username, "password": self.config.password})
        except Exception as exc: raise HarnessFailure("authentication_failed", stage="AUTH", exit_code=ExitCode.PREFLIGHT) from exc
        self.api.token = value.get("access_token")
        if not self.api.token: self.fail("authentication_failed", "AUTH", ExitCode.PREFLIGHT)
        self.known_secrets.append(self.api.token)

    def validate_input(self):
        if self.excel.suffix.lower() != ".xlsx" or not self.excel.is_file() or self.excel.stat().st_size <= 0:
            self.fail("input_invalid", "INPUT_VALIDATION", ExitCode.PREFLIGHT)
        try:
            book = load_workbook(self.excel, read_only=True); book.close()
        except Exception as exc: raise HarnessFailure("input_invalid", stage="INPUT_VALIDATION", exit_code=ExitCode.PREFLIGHT) from exc
        digest = hashlib.sha256(self.excel.read_bytes()).hexdigest()
        expected = (CANONICAL_SOURCE_SHA256 if self.excel == DEFAULT_EXCEL.resolve()
                    else self.config.expected_source_sha)
        if expected and expected != digest: self.fail("input_invalid", "INPUT_VALIDATION", ExitCode.PREFLIGHT)
        self.result["input"] = {"path": str(self.excel), "sha256": digest, "size_bytes": self.excel.stat().st_size}
        if expected: self.result["input"]["expected_sha256"] = expected

    def _exact_named(self, path: str, name: str): return [item for item in self.api.get(path)["items"] if item.get("name") == name]
    def _write_with_reread(self, write: Callable[[], dict], reread: Callable[[], list[dict]], stage: str):
        try: return write()
        except (requests.Timeout, requests.ConnectionError):
            winners = reread()
            if len(winners) == 1: return winners[0]
            if len(winners) > 1: self.fail("ambiguous_write", stage)
            try: return write()
            except (requests.Timeout, requests.ConnectionError) as exc: raise HarnessFailure("ambiguous_write", stage=stage) from exc

    def ensure_profile(self, profile_doc: dict):
        name = self.config.profile_name
        matches = self._exact_named("/v1/requirement-import-profiles", name)
        if len(matches) > 1: self.fail("fixture_ambiguous", "FIXTURE_PROFILE")
        if not matches:
            profile = self._write_with_reread(lambda: self.api.post("/v1/requirement-import-profiles", json={"name": name, "description": "Reserved automatic operator E2E fixture", "enabled": False}), lambda: self._exact_named("/v1/requirement-import-profiles", name), "FIXTURE_PROFILE")
        else: profile = matches[0]
        profile = self.api.get(f"/v1/requirement-import-profiles/{profile['profile_id']}")
        digest = canonical_sha256(ImportProfileDocument.model_validate(profile_doc).model_dump(mode="json"))
        exact = [v for v in profile.get("versions", []) if v.get("profile_sha256") == digest]
        if profile.get("versions") and (len(profile["versions"]) != 1 or len(exact) != 1): self.fail("fixture_drift", "FIXTURE_PROFILE")
        if not exact:
            version = self._write_with_reread(
                lambda: self.api.post(f"/v1/requirement-import-profiles/{profile['profile_id']}/versions", json={"profile": profile_doc}),
                lambda: [item for item in self.api.get(f"/v1/requirement-import-profiles/{profile['profile_id']}").get("versions", []) if item.get("profile_sha256") == digest],
                "FIXTURE_PROFILE",
            )
        else: version = exact[0]
        if version.get("status") == "draft":
            try: version = self.api.post(f"/v1/requirement-import-profiles/{profile['profile_id']}/versions/{version['version_number']}/approve")
            except (requests.Timeout, requests.ConnectionError):
                observed = self.api.get(f"/v1/requirement-import-profiles/{profile['profile_id']}")
                matches = [item for item in observed.get("versions", []) if item.get("profile_version_id") == version["profile_version_id"] and item.get("status") == "approved"]
                if observed.get("active_version_id") != version["profile_version_id"] or len(matches) != 1: self.fail("ambiguous_write", "FIXTURE_PROFILE")
                version = matches[0]
        elif version.get("status") != "approved": self.fail("fixture_drift", "FIXTURE_PROFILE")
        profile = self.api.get(f"/v1/requirement-import-profiles/{profile['profile_id']}")
        if profile.get("active_version_id") != version["profile_version_id"]: self.fail("fixture_drift", "FIXTURE_PROFILE")
        if not profile.get("enabled"):
            try: profile = self.api.patch(f"/v1/requirement-import-profiles/{profile['profile_id']}", json={"enabled": True})
            except (requests.Timeout, requests.ConnectionError):
                profile = self.api.get(f"/v1/requirement-import-profiles/{profile['profile_id']}")
                if not profile.get("enabled"): self.fail("ambiguous_write", "FIXTURE_PROFILE")
        self.result["fixtures"].update(profile_id=profile["profile_id"], profile_version_id=version["profile_version_id"])
        return profile, version

    def ensure_source(self, profile_id: str):
        name = self.config.source_name; matches = self._exact_named("/v1/requirement-sources", name)
        if len(matches) > 1: self.fail("fixture_ambiguous", "FIXTURE_SOURCE")
        expected = {"source_type": "manual_upload", "source_mode": "authoritative_snapshot", "source_config": {"display_name": "Requirement Operator E2E XLSX", "format": "xlsx"}, "import_profile_id": profile_id}
        if matches:
            source = matches[0]
            if any(source.get(key) != value for key, value in expected.items()): self.fail("fixture_drift", "FIXTURE_SOURCE")
        else:
            payload = {"name": name, **expected, "enabled": False}
            source = self._write_with_reread(lambda: self.api.post("/v1/requirement-sources", json=payload), lambda: self._exact_named("/v1/requirement-sources", name), "FIXTURE_SOURCE")
        if not source.get("enabled"):
            try: source = self.api.patch(f"/v1/requirement-sources/{source['source_id']}", json={"enabled": True})
            except (requests.Timeout, requests.ConnectionError):
                source = self.api.get(f"/v1/requirement-sources/{source['source_id']}")
                if not source.get("enabled"): self.fail("ambiguous_write", "FIXTURE_SOURCE")
        self.result["fixtures"]["source_id"] = source["source_id"]
        return source

    def import_requirements(self, source, version):
        data = self.excel.read_bytes(); files = {"file": (self.excel.name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        preview = self.api.post(f"/v1/requirement-sources/{source['source_id']}/preview?profile_version_id={version['profile_version_id']}", files=files, timeout=60)
        validate_preview(preview); self.pass_stage("REQUIREMENT_PREVIEW", accepted_count=3, rejected_count=0)
        source_sets_before = [item for item in self.api.get("/v1/requirement-sets")["items"] if item.get("source_id") == source["source_id"]]
        snapshot_ids_before = {
            snap.get("snapshot_id")
            for reqset in source_sets_before
            for snap in self.api.get(f"/v1/requirement-sets/{reqset['requirement_set_id']}/snapshots")["items"]
        }
        def winners():
            sets = [item for item in self.api.get("/v1/requirement-sets")["items"] if item.get("source_id") == source["source_id"]]
            found=[]
            for reqset in sets:
                for snap in self.api.get(f"/v1/requirement-sets/{reqset['requirement_set_id']}/snapshots")["items"]:
                    if snap.get("snapshot_id") not in snapshot_ids_before and snap.get("source_snapshot_sha256") == preview.get("source_sha256") and snap.get("import_profile_version_id") == version["profile_version_id"]: found.append({**snap, "requirement_set_id": reqset["requirement_set_id"], "status": "committed", "accepted_count": 3, "rejected_count": 0})
            return found
        committed = self._write_with_reread(lambda: self.api.post(f"/v1/requirement-sources/{source['source_id']}/import", files=files, timeout=60), winners, "REQUIREMENT_IMPORT")
        if committed.get("status") != "committed" or committed.get("accepted_count") != 3 or committed.get("rejected_count") != 0: self.fail("import_failed", "REQUIREMENT_IMPORT")
        sets = [item for item in self.api.get("/v1/requirement-sets")["items"] if item.get("source_id") == source["source_id"]]
        if len(sets) != 1: self.fail("snapshot_identity_mismatch", "SNAPSHOT")
        reqset = sets[0]
        if reqset.get("active_snapshot_id") != committed["snapshot_id"]: self.fail("snapshot_identity_mismatch", "SNAPSHOT")
        items = self.api.get(f"/v1/requirement-snapshots/{committed['snapshot_id']}/items")["items"]
        now = datetime.now(timezone.utc)
        if len(items) != 3 or any(item.get("expires_at") and self._dt(item["expires_at"]) <= now for item in items): self.fail("item_count_mismatch", "REQUIREMENT_ITEMS")
        self.result["fixtures"]["requirement_set_id"] = reqset["requirement_set_id"]
        self.result["requirement_import"] = {key: committed.get(key) for key in ("import_run_id", "snapshot_id", "accepted_count", "rejected_count")}
        return reqset, items

    @staticmethod
    def _dt(value): return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)

    def ensure_schedule(self, set_id: str):
        name = self.config.schedule_name; matches = self._exact_named("/v1/requirement-schedules?limit=100", name)
        if len(matches) > 1: self.fail("fixture_ambiguous", "SCHEDULE_FIXTURE")
        if matches:
            schedule = matches[0]
            if schedule.get("requirement_set_id") != set_id: self.fail("fixture_drift", "SCHEDULE_FIXTURE")
            if schedule.get("enabled"):
                try: schedule = self.api.patch(f"/v1/requirement-schedules/{schedule['schedule_id']}", json={"enabled": False})
                except (requests.Timeout, requests.ConnectionError):
                    schedule = self.api.get(f"/v1/requirement-schedules/{schedule['schedule_id']}")
                    if schedule.get("enabled"): self.fail("ambiguous_write", "SCHEDULE_FIXTURE")
        else:
            schedule = self._write_with_reread(lambda: self.api.post("/v1/requirement-schedules", json={"name": name, "requirement_set_id": set_id}), lambda: self._exact_named("/v1/requirement-schedules?limit=100", name), "SCHEDULE_FIXTURE")
        self.result["fixtures"]["schedule_id"] = schedule["schedule_id"]
        return schedule

    def schedule_and_wait(self, schedule, snapshot_id: str, expected_requirements: set[str]):
        sid = schedule["schedule_id"]
        baseline = {item["batch_run_id"] for item in self.api.get(f"/v1/requirement-schedules/{sid}/runs?limit=100")["items"]}
        anchor = (datetime.now(timezone.utc) + timedelta(seconds=self.config.anchor_lead_seconds)).replace(microsecond=0)
        payload = {"timezone": "UTC", "recurrence": {"kind": "interval", "every": 10080, "unit": "minutes", "anchor_at": anchor.isoformat()}, "run_policy": "all_active", "model": self.config.model}
        existing_versions = {item["schedule_version_id"] for item in self.api.get(f"/v1/requirement-schedules/{sid}").get("versions", [])}
        config_document = {"schema_version": 1, **payload}
        config_digest = hashlib.sha256(json.dumps(config_document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        def version_winners():
            return [item for item in self.api.get(f"/v1/requirement-schedules/{sid}").get("versions", []) if item.get("schedule_version_id") not in existing_versions and item.get("config_sha256") == config_digest]
        version = self._write_with_reread(lambda: self.api.post(f"/v1/requirement-schedules/{sid}/versions", json=payload), version_winners, "SCHEDULE_VERSION")
        self.result["fixtures"]["schedule_version_id"] = version["schedule_version_id"]
        self.pass_stage("SCHEDULE_VERSION", schedule_version_id=version["schedule_version_id"])
        try: self.api.post(f"/v1/requirement-schedules/{sid}/versions/{version['version_number']}/approve")
        except (requests.Timeout, requests.ConnectionError):
            observed = self.api.get(f"/v1/requirement-schedules/{sid}")
            if observed.get("active_version_id") != version["schedule_version_id"]: self.fail("ambiguous_write", "SCHEDULE_APPROVE")
        self.pass_stage("SCHEDULE_APPROVE")
        try: enabled = self.api.patch(f"/v1/requirement-schedules/{sid}", json={"enabled": True})
        except (requests.Timeout, requests.ConnectionError):
            enabled = self.api.get(f"/v1/requirement-schedules/{sid}")
            if not enabled.get("enabled") or enabled.get("active_version_id") != version["schedule_version_id"]: self.fail("ambiguous_write", "SCHEDULE_ENABLE")
        self.enabled_schedule_id = sid
        initial = self._dt(enabled["next_run_at"]); now = datetime.now(timezone.utc)
        if not now < initial <= now + timedelta(seconds=self.config.allowed_anchor_window_seconds): self.fail("next_run_at_out_of_window", "SCHEDULE_ENABLE")
        self.pass_stage("SCHEDULE_ENABLE", next_run_at=initial.isoformat())
        deadline = max(time.monotonic() + self.config.auto_claim_timeout_seconds, time.monotonic() + (initial-now).total_seconds() + 90)
        self.log("WAIT AUTO_CLAIM", schedule_id=sid, schedule_version_id=version["schedule_version_id"], scheduled_for=initial.isoformat())
        batch = None
        while time.monotonic() < deadline:
            listed = self.api.get(f"/v1/requirement-schedules/{sid}/runs?limit=100")["items"]
            runs = [self.api.get(f"/v1/requirement-schedules/{sid}/runs/{item['batch_run_id']}") for item in listed if item.get("batch_run_id") not in baseline]
            try: batch = classify_new_batch(runs, baseline, version["schedule_version_id"], snapshot_id, initial.isoformat()); break
            except HarnessFailure as exc:
                if str(exc) != "automatic_claim_timeout": raise
            time.sleep(2)
        if batch is None: self.fail("automatic_claim_timeout", "AUTO_CLAIM")
        self.log("CLAIMED", batch_run_id=batch["batch_run_id"])
        detail = self.api.get(f"/v1/requirement-schedules/{sid}/runs/{batch['batch_run_id']}")
        selected = [item for item in detail["items"] if item.get("selection_status") == "selected"]
        if len(selected) != 3 or {item.get("requirement_id") for item in selected} != expected_requirements: self.fail("item_count_mismatch", "RUN_SELECTION")
        advanced = self._dt(self.api.get(f"/v1/requirement-schedules/{sid}")["next_run_at"])
        validate_next_run(initial, advanced)
        try:
            disabled = self.api.patch(f"/v1/requirement-schedules/{sid}", json={"enabled": False}, timeout=30)
            if disabled.get("enabled") is not False: self.fail("cleanup_failed", "CLEANUP", ExitCode.CLEANUP)
            self.enabled_schedule_id = None
        except Exception as exc:
            raise HarnessFailure("cleanup_failed", stage="CLEANUP", exit_code=ExitCode.CLEANUP) from exc
        self.result["schedule"] = {"initial_next_run_at": initial.isoformat(), "scheduled_for": initial.isoformat(), "advanced_next_run_at": advanced.isoformat(), "trigger_type": "scheduled"}
        self.result["batch"] = {key: detail.get(key) for key in ("batch_run_id", "snapshot_id", "state", "selected_count", "skipped_count", "success_count", "failure_count", "phase1a_output_root_fingerprint")}
        for stage in ("AUTO_CLAIM", "RUN_IDENTITY", "RUN_SELECTION", "NEXT_RUN_ADVANCE"): self.pass_stage(stage)
        return detail

    def wait_terminal(self, batch):
        sid, bid = batch.get("schedule_id"), batch["batch_run_id"]
        if not sid: self.fail("automatic_claim_identity_mismatch", "RUN_IDENTITY")
        handoff_deadline = time.monotonic() + self.config.handoff_timeout_seconds
        previous_dispatched = None
        while time.monotonic() < handoff_deadline:
            batch = self.api.get(f"/v1/requirement-schedules/{sid}/runs/{bid}")
            failure = terminal_failure(batch)
            if failure: self.fail(failure, "REMOTE_EXECUTION")
            selected = [x for x in batch["items"] if x.get("selection_status") == "selected"]
            dispatched = sum(bool(x.get("remote_job_id") and x.get("dispatched_at")) for x in selected)
            if dispatched != previous_dispatched:
                self.log("WAIT HANDOFF" if dispatched == 0 else "HANDOFF", dispatched=f"{dispatched}/3")
                for item in selected:
                    if item.get("remote_job_id"):
                        self.log("ITEM", **{key: item.get(key) for key in (
                            "run_item_id", "requirement_id", "remote_job_id", "remote_job_state", "execution_state",
                        )})
                previous_dispatched = dispatched
            if len(selected) == 3 and all(x.get("remote_job_id") and x.get("dispatched_at") for x in selected): break
            time.sleep(2)
        else: self.fail("handoff_timeout", "HANDOFF")
        validate_remote_items(batch["items"]); self.pass_stage("HANDOFF"); self.pass_stage("REPORT_JOBS")
        started = time.monotonic(); deadline = started + self.config.remote_timeout_seconds
        last_signature = None; last_log_at = float("-inf")
        self.log("WAIT REMOTE_EXECUTION", batch_run_id=bid, timeout_seconds=self.config.remote_timeout_seconds)
        while time.monotonic() < deadline:
            batch = self.api.get(f"/v1/requirement-schedules/{sid}/runs/{bid}")
            now = time.monotonic()
            summary, _items, signature = self._progress_snapshot(batch)
            elapsed = max(0, int(now - started)); remaining = max(0, int(deadline - now))
            if signature != last_signature:
                self._log_progress_snapshot("REMOTE_EXECUTION", batch, elapsed_seconds=elapsed, remaining_seconds=remaining)
                last_signature, last_log_at = signature, now
            elif now - last_log_at >= self.PROGRESS_HEARTBEAT_SECONDS:
                self.log("REMOTE_EXECUTION", heartbeat=True, completed=summary["completed"], elapsed_seconds=elapsed, remaining_seconds=remaining)
                last_log_at = now
            failure = terminal_failure(batch)
            if failure: self.fail(failure, "REMOTE_EXECUTION")
            if all(x.get("remote_job_state") == "completed" and x.get("execution_state") == "completed" for x in batch["items"] if x.get("selection_status") == "selected") and batch.get("state") == "completed": break
            time.sleep(3)
        else:
            self._log_progress_snapshot("TIMEOUT REMOTE_EXECUTION", batch, timeout_seconds=self.config.remote_timeout_seconds)
            self.fail("remote_execution_timeout", "REMOTE_EXECUTION")
        validate_terminal(batch)
        for stage in ("REMOTE_EXECUTION", "ARTIFACT_RECONCILIATION", "RUN_ITEMS_TERMINAL", "BATCH_TERMINAL"): self.pass_stage(stage)
        return batch

    def verify_artifacts(self, batch):
        persisted_root = batch.get("phase1a_output_root_fingerprint")
        if persisted_root != self.result["deployment_evidence"].get("artifact_root_fingerprint"):
            self.fail("artifact_root_fingerprint_mismatch", "ARTIFACT_RECONCILIATION")
        for item in batch["items"]:
            if item.get("selection_status") != "selected": continue
            evidence = self.evidence_provider.verify_artifact(
                {**item, "batch_run_id": batch["batch_run_id"]}, persisted_root,
                self.output / "artifacts" / f"{item['run_item_id']}.docx")
            self.result["artifacts"].append({"run_item_id": item["run_item_id"], **evidence})
            self.result["items"].append({key: item.get(key) for key in ("run_item_id", "requirement_id", "remote_job_id", "remote_job_state", "execution_state", "artifact_relative_path", "artifact_sha256")})
        if len(self.result["artifacts"]) != 3: self.fail("artifact_missing", "ARTIFACT_RECONCILIATION")
        self.pass_stage("DOCX_INTEGRITY", count=3); self.pass_stage("SHA256_MATCH", count=3)

    def run(self):
        self.pass_stage("CONFIG_PREFLIGHT")
        try: health = self.api.get("/healthz", timeout=30)
        except Exception as exc: raise HarnessFailure("api_unreachable", stage="API_READINESS", exit_code=ExitCode.PREFLIGHT) from exc
        self.pass_stage("API_READINESS", status=health.get("status")); self.authenticate(); self.pass_stage("AUTH")
        self.api.get("/v1/requirement-import-profiles"); self.api.get("/v1/requirement-schedules")
        self.pass_stage("PIPELINE_READINESS")
        if self.config.mode == "local":
            self.evidence_provider = LocalDeploymentEvidenceProvider(PROJECT_ROOT, self.config.artifact_root)
        else:
            self.evidence_provider = RemoteDeploymentEvidenceProvider(self.api)
        deployment_evidence = self.evidence_provider.preflight()
        self.result["deployment_evidence"] = deployment_evidence
        self.result["deployment_source"] = deployment_evidence.get("deployment_source", self.result["operator_source"])
        _validate_deployment_source(
            self.result["deployment_source"],
            self.result["operator_source"]["provenance_fingerprint"],
            self.config.expected_runtime_sha,
        )
        self.pass_stage("RUNTIME_WORKERS", workers=deployment_evidence["workers"])
        self.validate_input(); self.pass_stage("INPUT_VALIDATION")
        profile_doc = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        profile, version = self.ensure_profile(profile_doc); self.pass_stage("FIXTURE_PROFILE")
        source = self.ensure_source(profile["profile_id"]); self.pass_stage("FIXTURE_SOURCE")
        reqset, items = self.import_requirements(source, version)
        for stage in ("REQUIREMENT_IMPORT", "SNAPSHOT", "REQUIREMENT_ITEMS"): self.pass_stage(stage)
        schedule = self.ensure_schedule(reqset["requirement_set_id"]); self.pass_stage("SCHEDULE_FIXTURE")
        batch = self.schedule_and_wait(schedule, self.result["requirement_import"]["snapshot_id"], {x["requirement_id"] for x in items})
        batch = self.wait_terminal(batch); self.verify_artifacts(batch)
        self.result["batch"].update({key: batch.get(key) for key in ("state", "success_count", "failure_count")})

    def cleanup(self):
        if self.enabled_schedule_id:
            self.api.patch(f"/v1/requirement-schedules/{self.enabled_schedule_id}", json={"enabled": False}, timeout=30)
            self.enabled_schedule_id = None
        self.pass_stage("CLEANUP")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Before live execution:

1. Copy operator_e2e/e2e.env.example
   to operator_e2e/e2e.env.local.
2. Fill deployment-local values and credentials.
3. Transfer the release provenance with the reviewed package.
4. Use --mode local on the Linux deployment host, or --mode remote from an operator workstation.

Windows/Spyder is supported for remote-operator acceptance.
Local-host acceptance remains Linux deployment-host only.""",
    ); parser.add_argument("--mode", choices=("local", "remote"), default="local",
                           help="local: Linux deployment host; remote: Windows/POSIX operator workstation")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL,
                        help="XLSX override (default: canonical fixture resolved beside this script)")
    parser.add_argument("--provenance", type=Path, default=PROJECT_ROOT / PROVENANCE_NAME,
                        help="release provenance (default: repository-root canonical artifact)")
    parser.add_argument("--output-dir", type=Path); parser.add_argument("--env-file", type=Path, default=SCRIPT_DIR / "e2e.env.local")
    return parser.parse_args(argv)


def _provenance_source(root: Path, path: Path, expected_runtime_sha: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise HarnessFailure("release_provenance_missing", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
    try:
        provenance = load_provenance(path)
        verify_package_files(root, provenance)
    except ValueError as exc:
        category = ({"active_runtime_source_mismatch": "operator_runtime_source_mismatch",
                     "unexpected_runtime_input": "unexpected_runtime_input"}.get(
                         str(exc), "release_provenance_invalid"))
        raise HarnessFailure(category, stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT) from exc
    if expected_runtime_sha and expected_runtime_sha != provenance["reviewed_runtime_sha"]:
        raise HarnessFailure("legacy_runtime_sha_mismatch", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
    return {
        "repository": provenance["repository"], "identity_kind": "release_provenance",
        "identity_verified": True, "reviewed_runtime_sha": provenance["reviewed_runtime_sha"],
        "runtime_files": provenance["runtime_files"],
        "provenance_fingerprint": provenance_fingerprint(provenance),
        "legacy_expected_runtime_sha": expected_runtime_sha,
    }


def _validate_deployment_source(source: dict[str, Any], expected_fingerprint: str,
                                legacy_expected_sha: str | None = None) -> None:
    if not source.get("identity_verified"):
        raise HarnessFailure("deployment_source_identity_mismatch", stage="RUNTIME_WORKERS", exit_code=ExitCode.PREFLIGHT)
    if source.get("provenance_fingerprint") != expected_fingerprint:
        raise HarnessFailure("deployment_provenance_identity_mismatch", stage="RUNTIME_WORKERS",
                             exit_code=ExitCode.PREFLIGHT)
    if legacy_expected_sha and source.get("reviewed_runtime_sha") != legacy_expected_sha:
        raise HarnessFailure("deployment_source_provenance_mismatch", stage="RUNTIME_WORKERS",
                             exit_code=ExitCode.PREFLIGHT)


def main(argv=None) -> int:
    bootstrap_env(); args = parse_args(argv); run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    result = result_document(run_id, args.mode); started = time.monotonic(); harness = None; diagnostics = {"logs": {}}
    # This fallback exists solely so CONFIG failures can still publish evidence.
    # Once configuration is valid, its resolved (or CLI-overridden) directory is
    # authoritative for the lock, artifact copies, and final evidence alike.
    evidence_output = (args.output_dir or Path("operator_e2e/output/requirement_e2e")) / run_id
    try:
        validate_live_platform(args.mode)
        production_artifact_root = None
        if args.mode == "local":
            try:
                from config.deployment_bootstrap import requirement_handoff_output_root
                production_artifact_root = requirement_handoff_output_root(PROJECT_ROOT)
            except FileNotFoundError:
                production_artifact_root = None
            except Exception as exc:
                raise HarnessFailure(
                    "configuration_error", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT,
                ) from exc
        if not args.env_file.exists() and not has_usable_requirement_process_configuration(
            dict(os.environ), args.mode, production_artifact_root=production_artifact_root,
        ):
            raise HarnessFailure(
                "configuration_file_missing", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT,
            )
        env = load_e2e_environment(args.env_file, dict(os.environ))
        evidence_output = (args.output_dir or Path(env.get("SRA_E2E_OUTPUT_DIR") or "operator_e2e/output/requirement_e2e")) / run_id
        config = E2EConfig.from_environment(
            env, args.mode, production_artifact_root=production_artifact_root,
        )
        if args.output_dir: config = E2EConfig(**{**config.__dict__, "output_dir": args.output_dir})
        evidence_output = config.output_dir / run_id
        harness = Harness(config, args.excel.resolve(), run_id, result)
        result["operator_source"] = _provenance_source(
            PROJECT_ROOT, args.provenance.resolve(), config.expected_runtime_sha,
        )
        with SingleRunLock(config.output_dir / ".lock", args.mode):
            try: harness.run()
            finally:
                try: harness.cleanup()
                except Exception as cleanup_exc: raise HarnessFailure("cleanup_failed", stage="CLEANUP", exit_code=ExitCode.CLEANUP) from cleanup_exc
        result.update(overall_status="PASS", exit_code=0); exit_code = ExitCode.PASS
    except HarnessFailure as exc:
        result.update(overall_status="FAIL", exit_code=int(exc.exit_code), failed_stage=exc.stage, failure_category=str(exc)); exit_code = exc.exit_code
        if exc.stage:
            stage = next((x for x in result["stages"] if x["name"] == exc.stage), None)
            if stage: stage["status"] = StageStatus.FAIL
        if harness:
            paths = {"api": harness.config.api_log_path, "schedule": harness.config.schedule_log_path, "handoff": harness.config.handoff_log_path}
            diagnostics["logs"] = {name: bounded_log_tail(path if path.is_absolute() else PROJECT_ROOT / path, harness.known_secrets) for name, path in paths.items()}
    except Exception:
        result.update(overall_status="FAIL", exit_code=4, failure_category="internal_harness_error"); exit_code = ExitCode.INTERNAL
    result["finished_at"] = datetime.now(timezone.utc).isoformat(); result["duration_seconds"] = round(time.monotonic() - started, 3)
    try:
        known_secrets = harness.known_secrets if harness else []
        final_evidence_stage = next(item for item in result["stages"] if item["name"] == "FINAL_EVIDENCE")
        final_evidence_stage.update(status=StageStatus.PASS, evidence={})
        evidence_output.mkdir(parents=True, exist_ok=False)
        (evidence_output / "artifacts").mkdir()
        safe = redact(result, known_secrets)
        atomic_write_json(evidence_output / "result.json", safe)
        atomic_write_json(evidence_output / "diagnostics.json", redact(diagnostics, known_secrets))
        summary = f"REQUIREMENT_E2E = {result['overall_status']}\nACCEPTANCE_MODE = {args.mode}\nFRESH_LIVE_REQUIREMENT_E2E_PASS = {'YES' if result['overall_status'] == 'PASS' else 'NO'}\nEXIT_CODE = {int(exit_code)}\n"
        if result.get("failed_stage"): summary += f"FAILED_STAGE = {result['failed_stage']}\nFAILURE_CATEGORY = {result['failure_category']}\n"
        atomic_write_text(evidence_output / "summary.txt", summary)
        if harness: harness.log("PASS FINAL_EVIDENCE")
    except FileExistsError:
        # Artifact verification may already have created this invocation's unique
        # directory; only the expected directory itself may pre-exist.
        try:
            evidence_output.mkdir(parents=True, exist_ok=True)
            (evidence_output / "artifacts").mkdir(exist_ok=True)
            atomic_write_json(evidence_output / "result.json", redact(result, known_secrets))
            atomic_write_json(evidence_output / "diagnostics.json", redact(diagnostics, known_secrets))
            summary = f"REQUIREMENT_E2E = {result['overall_status']}\nACCEPTANCE_MODE = {args.mode}\nFRESH_LIVE_REQUIREMENT_E2E_PASS = {'YES' if result['overall_status'] == 'PASS' else 'NO'}\nEXIT_CODE = {int(exit_code)}\n"
            if result.get("failed_stage"): summary += f"FAILED_STAGE = {result['failed_stage']}\nFAILURE_CATEGORY = {result['failure_category']}\n"
            atomic_write_text(evidence_output / "summary.txt", summary)
            if harness: harness.log("PASS FINAL_EVIDENCE")
        except Exception:
            exit_code = ExitCode.INTERNAL
            result.update(overall_status="FAIL", exit_code=4, failed_stage="FINAL_EVIDENCE", failure_category="evidence_write_failed")
            next(item for item in result["stages"] if item["name"] == "FINAL_EVIDENCE")["status"] = StageStatus.FAIL
    except Exception:
        exit_code = ExitCode.INTERNAL
        result.update(overall_status="FAIL", exit_code=4, failed_stage="FINAL_EVIDENCE", failure_category="evidence_write_failed")
        next(item for item in result["stages"] if item["name"] == "FINAL_EVIDENCE")["status"] = StageStatus.FAIL
    print(f"REQUIREMENT_E2E = {result['overall_status']}")
    if result.get("failed_stage"): print(f"FAILED_STAGE = {result['failed_stage']}\nFAILURE_CATEGORY = {result['failure_category']}")
    if result.get("failure_category") == "configuration_file_missing":
        print("Create operator_e2e/e2e.env.local first.\nStart from operator_e2e/e2e.env.example.")
    elif result.get("failure_category") == "unsupported_local_platform":
        print(
            "Requirement Automatic Operator E2E live acceptance must be run on the Linux deployment host.\n\n"
            "Windows/Spyder is supported for remote-operator acceptance with --mode remote.\n"
            "Local-host acceptance remains Linux deployment-host only.\n\n"
            "On the Linux host, first copy:\noperator_e2e/e2e.env.example\n\nto:\n"
            "operator_e2e/e2e.env.local"
        )
    return int(exit_code)


if __name__ == "__main__": raise SystemExit(main())
