# Future Requirement Task Center / Operator Workflow — Discussion Notes

**Status: FUTURE / NOT STARTED**

**Authority: discussion and requirements capture only**

**Not a Design**

**Not an Implementation Plan**

**Must be reconciled against actual main before Design v1**

## Purpose and historical boundary

This note prevents a future operator-workflow requirement from being lost. It does not authorize implementation, decide final architecture, or expand any executed or superseded Phase 1B / Phase 1C Design or Implementation Plan. Historical statements—including Phase 1B Web UI exclusions—remain true for the scope and repository snapshot those documents governed. No plan version, supersedes relationship, phase number, or historical status is changed here.

The future work must follow this gate sequence:

```text
current-main rebaseline
→ Requirement Task Center Design v1
→ human/ChatGPT Design review/approval
→ Implementation Plan v1
→ Codex execution prompt
→ implementation
```

There is no authoritative phase number assigned here. The work is called **Future Requirement Task Center / Operator Workflow**, not “Phase 1D.”

## Intended operator experience

```text
Authorized operator signs in
→ opens Requirement Task Center in/alongside SRA Editor
→ uploads XLSX/CSV/JSON Requirement source
→ Preview shows accepted/rejected/expired/classification results
→ operator explicitly confirms Import
→ committed Import creates Requirement/Snapshot state
→ operator chooses:
     A. Execute now
     B. Create/update recurring Schedule
→ background execution uses existing Schedule/Batch/Handoff/Report Job engine
→ GUI shows Batch and per-item progress
→ completed artifacts become downloadable through authorized HTTP endpoints
```

The Task Center should make this workflow simple, legible, and safe. Simplicity is not permission bypass: import and mutation require an appropriately privileged operator, and high-risk enablement or approval remains superuser-gated wherever current source requires it. Design v1 must reconcile every action with actual current-main RBAC and audit behavior.

## Future capabilities to evaluate in Design v1

- Requirement source upload for XLSX, CSV, and JSON.
- Preview and diagnostic review, including accepted, rejected, expired, and classification results.
- Explicit Confirm Import.
- Requirement Set and immutable Snapshot visibility.
- Immediate execution and recurring schedule configuration.
- Run policy selection and model selection.
- `next_run_at` display.
- Schedule enable/disable according to RBAC.
- Batch history and Batch state/progress.
- Selected, completed, and failure counts.
- Per-Requirement execution state and safe error display.
- Per-item DOCX download, download-all ZIP, and result/manifest Excel export.
- Retry or cancel only if separately designed later; this note does not authorize or define either behavior.

These are requirements for later design analysis, not final widgets, routes, payloads, state machines, or API contracts.

## Import and execution are separate authorized actions

**Uploading/importing Excel does NOT silently mean “execute reports immediately”.** The same separation applies to every supported source format.

The UI may make “Import and execute now” feel like one short operator workflow, but its internal actions must remain explicit and authorized so an operator can choose:

```text
import only
execute now
or schedule execution
```

Import commits Requirement, RequirementVersion, Requirement Set, and Snapshot control-plane state. Execution materializes a Batch Run against an exact authorized Snapshot and Schedule version. A later Design must preserve this boundary rather than collapsing import into implicit report dispatch.

## Reuse the implemented engines

The Task Center is an operator orchestration surface over existing authorities. It should coordinate, not replace or redesign merely for GUI convenience:

- Requirement Import;
- Requirement Set / Snapshot;
- Requirement Schedule;
- Batch Run / Run Item;
- Schedule Worker;
- Handoff Worker;
- Report Job;
- Agent / Elasticsearch / LLM; and
- DOCX reconciliation.

JT-1 Job Task orchestration, LangGraph integration, and launcher/startup work remain separate future or operational boundaries. This note neither pulls them into the Task Center nor changes their status.

## Critical browser and download boundary

The future browser GUI must **not**:

- expose `REQUIREMENT_HANDOFF_CREDENTIAL`;
- use the Handoff Service Key in the browser;
- expose raw server filesystem paths as the user download contract; or
- depend on direct access to `artifact_relative_path`.

Design v1 should consider owner- and RBAC-aware HTTP artifact resources conceptually shaped as:

```text
batch → run item → authorized DOCX download
batch → authorized ZIP bundle
batch → authorized result Excel/manifest
```

Exact routes, request/response models, authorization rules, storage resolution, retention behavior, and bundle/export generation are **not decided in this note**. Final API contracts must not be invented before Design v1 and its review.

## Current implementation evidence and limits

Current source already provides Requirement preview/commit and Requirement Set/Snapshot visibility, schedule lifecycle/manual run/history surfaces, SQL-authoritative Batch/Run Item state, independent Schedule and Handoff workers, owner-scoped Report Jobs, and DOCX reconciliation. Those boundaries are inputs to the future rebaseline, not permission to assume that the eventual browser contract already exists.

Externally supplied operator evidence dated 2026-09-10 establishes only:

> **three-item automatic technical Golden Path deployment acceptance = PASS**

The scheduled Batch selected three items with no skips; three distinct owner-scoped Report Jobs completed; three DOCX artifacts passed ZIP validity and persisted-SHA256 checks; the Batch completed; `next_run_at` advanced automatically; and both Schedule and Handoff workers remained alive. This does **not** establish complete Phase 1B/1C deployment acceptance. Schema migration matrices, rollback/failure injection, fencing/failover, concurrency/races, HA, and all security-rotation gates remain outside that evidence.

Elasticsearch/topic data coverage is intentionally incomplete during POC. Content misses caused by incomplete test data are not evidence that the technical Schedule/Handoff/Report Job automation chain failed. No production content-quality acceptance is claimed.

## Non-goals of this note

- No UI, API, download, export, retry, cancel, worker, persistence, or workflow behavior is implemented.
- No current engine is redesigned or replaced.
- No Design or Implementation Plan is created.
- No existing Design/Plan scope is expanded or historical NOT STARTED statement rewritten, except the narrow deployment-acceptance status superseded by supplied live evidence in the backlog.
- No JT-1, LangGraph, launcher/startup, or invented phase-number work is included.
