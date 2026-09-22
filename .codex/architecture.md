# System Architecture

## 2026-09-20 Requirement registry verifier trust boundary

- `shared.runtime_provenance.verify_package_files()` performs generic byte and discovered-input verification without consulting ambient environment for Requirement SQL registry classification. Its optional `selected_registry` input is an explicit trust-boundary value.
- `sra_api.services.requirement_e2e_runtime_evidence.collect_source_evidence()` is the Linux deployment boundary that resolves the actual selector and passes only its repository-relative identity into verification. The identity is used for rejection only and is never returned in runtime evidence. Remote operator preflight performs generic verification, then relies on authenticated deployment evidence and the canonical provenance fingerprint.

## Current Summary

- The repository is a FastAPI + Elasticsearch RAG/agent system. `app.py` is the root ASGI entrypoint; `api/` is a compatibility namespace for the implementation in `sra_api/`. Agent/retrieval lives in `agent/`, ingestion in `data_ingestion/`, Requirement scheduling in `requirement_scheduler/`, and operator acceptance tooling in `operator_e2e/`.
- Chat flows through bounded routing/refinement views while preserving full user content at execution. Agent modes route to report, style, document-follow-up, or direct LLM paths. Elasticsearch supplies retrieval evidence; presenters render Markdown/DOCX.
- Requirement import uses SQL Server-backed immutable Sets, Versions, Snapshots, and Import Runs. Scheduling uses separate launcher-supervised Schedule and Handoff workers; the API lifespan owns the Report Job worker. Durable SQL state is the process boundary.
- `run_sra_api.sh` supervises API, Schedule Worker, and Handoff Worker with fail-closed process/listener identity and deployment bootstrap. Report Job artifacts are root-confined and digest checked.
- The operator E2E Harness supports local Linux and remote/offline operator modes. Canonical release authority is schema-v2 `REQUIREMENT_E2E_PROVENANCE.json`; its canonical SHA-256 fingerprint is cross-host identity. Git SHA is audit metadata, not deployment acceptance authority.
- `shared/runtime_provenance.py` is the shared authority for provenance paths, generated-product exclusions, module namespaces, CRLF source equivalence, exact package-byte checks, and bounded runtime-input discovery.
- The selected Requirement SQL registry is always deployment-local authority. Shared policy derives its repository-relative member only when selected inside the project root; generation excludes exactly that member, and package acceptance rejects a manifest containing it before reading its bytes.
- Bounded runtime-input discovery covers direct-child case-insensitive manual-synonym JSON files and actually selected index YAML and Editor form configuration. The Requirement SQL registry is privileged deployment-local configuration resolved through the shared selector, never release provenance. Existing selected external release-managed files fail closed as unattested. Mutable/deployment-local inputs such as dotenv, credentials, auth/session stores, SQLite databases, generated outputs, and operator-managed import/task data are not release provenance.
- Incremental deployment remains supported: inactive residue is not blanket rejected. Unreviewed inactive Python is warning-only, while an actually imported project module outside provenance remains blocking; namespace shadowing also remains blocking.
- Auth roles are `data_reader`, `data_editor`, `db_operator`, and `superuser`. Editor/session authentication and Service Keys remain distinct boundaries. Signed browser resources use action/representation-bound HMAC capabilities.
- Excel-to-SQL dashboard/task files are operator-managed deployment configuration and mutable workflow state; SQL-to-ES and Requirement source files are explicit operator inputs rather than implicitly auto-loaded release assets.

## Recent Changes

### 2026-09-22 Handoff lease lifecycle

- Each production coordinator work cycle owns one non-daemon heartbeat thread that renews the same owner/token/fencing generation at the configured heartbeat interval while authoritative work is active. The synchronized in-memory proof may advance only by successful renewal.
- Heartbeat loss invalidates that proof; SQL store mutations remain protected by `_prove_lease`, and coordinator stage boundaries reject missing or changed authority. Exact lease contention/loss returns to bounded acquisition polling, while all other failures remain fatal. Shutdown stops and joins the heartbeat before releasing a valid current lease.
- Joined work/heartbeat errors use fatal-first deterministic precedence, so a recoverable lease error cannot mask an invariant failure. Stop requests are also checked after reconciliation and prepare, preventing shutdown from starting a new prepare or submit stage.
- Process stop and heartbeat stop are distinct: SIGTERM/SIGINT closes future stage/cycle admission, while the non-daemon heartbeat continues renewing throughout the current in-flight authoritative call. Only the work-cycle cleanup boundary sets `heartbeat_stop` and joins the thread.

### 2026-09-20 Deployment registry and empty-synonym correction

- Removed the private Requirement SQL registry from release-provenance discovery while retaining one shared path selector for API, workers, and bootstrap.
- An explicitly empty `MANUAL_SYNONYMS_DIR` now disables external synonym discovery; an absent key still selects `config/synonyms`, and non-empty directories retain direct-child case-insensitive JSON enforcement.

### 2026-09-18 Bounded runtime-input provenance closure

- Added one pure shared resolver policy consumed by runtime loaders, package generation, deployment evidence, and offline package verification.
- Package generation rejects untracked auto-loaded synonym JSON. Deployment and offline verification require all actually selected release-managed inputs to be provenance members before mutation, with stable `unexpected_runtime_input` propagation.
- Exact byte hashing, provenance fingerprinting, active-module membership, namespace shadow checks, worker identity, and artifact-root checks remain unchanged.

### 2026-09-18 Release identity hardening

- Schema-v2 provenance hashes actual package bytes, allows only explicit LF-to-CRLF source equivalence during external generation, and never normalizes deployment verification.
- Generated `operator_e2e/output/**` and root report DOCX files are excluded while operator code/config and the canonical XLSX remain managed.

### 2026-09-16 Requirement operator E2E Harness v2

- Local/remote evidence providers share the same acceptance flow. The authenticated superuser runtime-evidence endpoint exposes bounded provenance, worker, and artifact-root facts; published artifact evidence validates root confinement, DOCX shape, and digest.

### 2026-09-10 Requirement runtime automation

- The unified launcher and deployment bootstrap supervise API, Schedule Worker, and Handoff Worker. Schedule materialization and handoff communicate only through durable SQL-authoritative Batch/Run Item state.

## Archived History

- `.codex/archive/architecture.md-20260918-000000.md` — full pre-compaction architecture through 2026-09-18.
- Earlier archives referenced by that file remain under `.codex/archive/`.
