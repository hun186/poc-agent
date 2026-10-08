# Known Issues

## Current Summary

- Formal Requirement deployment acceptance is not complete. Repository tests and documentation review are not substitutes for authorized live SQL Server, Elasticsearch, external LLM, Agent, Schedule/Handoff, artifact, and DOCX verification.
- Live Requirement acceptance is specifically blocked by the unresolved Elasticsearch `mapping_incompatible` capability/mapping condition. Correct the live mapping issue and rerun authorized capability plus end-to-end acceptance before claiming deployment PASS.
- Unified launcher/deployment Gates SD-1 through SD-7 and real safe-restart/takeover behavior still require operator verification in the deployed SRA container.
- The execution environment may block direct Git/package-index network access through proxy/DNS restrictions. Hosted GitHub connector operations can still be available independently; installed requirements have allowed repository work when package downloads were unavailable.
- Browser/Playwright runtime is unavailable here; UI work can use static DOM/JavaScript/API tests but still requires browser-capable acceptance.
- Private Requirement SQL Server and SRA/Elasticsearch deployment credentials/configuration are not available in this repository environment.
- Direct `pytest` may omit the repository root from `sys.path` in this container; `python -m pytest` is the verified invocation style.
- Excel-to-SQL may emit `datetime.utcnow` deprecation warnings and FastAPI/Starlette TestClient compatibility warnings.

## Open Issues

### Requirement deployment acceptance

- Resolve live Elasticsearch `mapping_incompatible`, then rerun mapping/capability verification and the real Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX flow.
- Run fresh/migrated SQL schema/catalog validation, rollback/failure injection, fencing/failover, concurrency/races, HA, credential rotation, and production content-quality acceptance in an authorized environment.
- The previously observed single-item and three-item technical Golden Paths do not close these broader matrices and must not be restated as fresh acceptance.

### Launcher and deployment lifecycle

- Run `./run_sra_api.sh` in the actual SRA container against the existing listener and verify the intended API process receives TERM, port 9002 is released, API/Schedule/Handoff replacements start, SQL lease authority remains correct, and no unrelated process is signaled.
- Manifest-enabled package/overlay trust-chain tooling exists, but live SD-1 through SD-7 evidence remains pending; do not retroactively bless an old deployment tree.

### Retrieval exclusion boundary

- Report instructions can keep an excluded term out of core-term selection, but downstream synonym expansion still lacks a structured exclusion contract. Contextual disambiguation is mitigation, not a hard guarantee.

### Runtime/provenance observation limits

- Python cannot safely inventory every dynamically loaded module in separate Schedule/Handoff worker processes without additional IPC/instrumentation. Current provenance positively binds managed runtime files and worker entry identities; stronger per-process loaded-module attestation requires separate design.
- Deployment-local Requirement SQL registry remains privileged configuration and is intentionally outside release-provenance contents/hash disclosure.

### Verification environment caveats

- Historical combined full-suite runs exposed order-dependent/pre-existing failures and launcher timing sensitivity while focused required suites passed. These records are preserved in archive; do not reinterpret them as a current full-suite PASS or current production defect without re-running on the relevant head.
- Remote/live operator execution requires valid ignored/process configuration for deployment URL, model, and authorized superuser session credentials. Do not substitute a Service Key where a user-session authority is required.
- Signed URLs remain bearer capabilities until expiry; service-key persistence and local Report Job SQLite/artifacts are not multi-machine HA.

## Recent Changes

- 2026-10-06: P1.0A PR #279 verification again confirmed direct Git transport is unavailable in this execution environment (`git ls-remote` failed with `Could not resolve host: github.com`). Therefore no local pytest PASS is claimed for this branch; Hosted review/check evidence remains required.

- 2026-10-06: P1.0 re-review again confirmed the execution container cannot resolve `github.com` for a direct clone, so local pytest could not be run on the hosted branch; Hosted GitHub connector inspection/checks remain available and must not be represented as local pytest.
- 2026-10-06: Restored the unresolved Elasticsearch `mapping_incompatible` blocker to active memory/known issues during PR #277 compaction review.
- 2026-09-30: Hosted GitHub connector remained usable for PR work while direct Git transport from the execution container was unavailable; no local pytest result was claimed for that corrective.
- 2026-09-22: Capability-adaptive E2E established offline boundary verification but did not perform FULL_LIVE/HYBRID deployment acceptance.
- 2026-09-16: Harness v2/provenance work retained explicit live-environment and cross-process observation limits.

## Archived History

- `.codex/archive/known_issues.md-20261006-153400.md` — complete active known-issues file immediately before this compaction, including all prior dated environment/deployment/provenance records.
- `.codex/archive/known_issues.md-20260910-070805.md` — earlier full pre-compaction known-issues history.
- Older archive references remain discoverable from those preserved files.

## Compaction Record

- 2026-10-06: Compacted active `.codex/known_issues.md` after robust date/work-block counting exceeded the AGENTS.md >20 trigger. Full text was archived first; unresolved acceptance blockers, environment constraints, retrieval limitation, launcher work, and provenance observation limits remain active.


- 2026-10-07: P1.2 local verification reconfirmed the execution container cannot resolve `github.com` (`git ls-remote` -> `Could not resolve host: github.com`). The hosted branch therefore cannot be cloned for local pytest; do not claim a local pytest PASS. Use Hosted source inspection, Vercel/check status, and exact-head Codex review for this slice.


- 2026-10-07: P1.3 local verification again cannot clone/read Hosted Git through direct transport because `github.com` DNS resolution fails. No local pytest PASS is claimed for the one-time create saga; Hosted source inspection, exact-head Codex review, and Hosted checks are the available repository verification evidence.


- 2026-10-08 P1.5 local verification remains unavailable because direct Git transport cannot resolve `github.com` in this execution environment. No local pytest PASS is claimed; use Hosted source inspection, exact-head Codex review, and Hosted checks for this branch.
