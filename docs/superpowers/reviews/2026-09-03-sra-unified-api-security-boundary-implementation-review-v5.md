# SRA Unified API Security Boundary — Implementation Review v5

## Verdict

**PASS for repository implementation / security gate.**

**Deployment acceptance remains PENDING / NOT EXECUTED** until the operator environment completes the mandatory real Service Key → Router → Elasticsearch retrieval → long-running report Agent → report synthesis → signed Word → valid DOCX chain.

No Design v4 is required. No additional implementation plan is required unless the real deployment E2E exposes a functional/security defect.

> Version note: a prior `Implementation Review v4` was issued only to record a snapshot mismatch when the ZIP had not yet pulled the Codex resulting source. This review uses the corrected pulled source and is therefore numbered v5 rather than overwriting that record.

## Baseline

- Source snapshot: `poc-agent_20260903-170320.zip`
- Repository/branch from prior Codex execution report: `/workspace/poc-agent`, branch `work`
- Reported Codex resulting commit: `eb32b2272a3215c5b6f263faf0233e5dbbbaf0e0`
- Commit identity is **not independently verifiable from this ZIP** because Git metadata is not included; the ZIP is the authoritative review baseline.
- Design: v3
- Authoritative pre-implementation review: v3
- Implementation Plan: v6.1
- Review v2 traceability artifact: restored and present

## Source conformity to Plan v6.1

### PASS — direct signed-resource scope denial audit

`require_principal_or_capability()` now emits `security.authorization_denied` with safe principal metadata and required scope before returning HTTP 403 for a valid authenticated principal that lacks the direct-resource scope. Capability fallback and invalid-Authorization precedence remain unchanged.

### PASS — Report Job owner mismatch audit with 404 concealment

Status and download routes now distinguish:

- nonexistent Job → 404, no fabricated owner-mismatch audit;
- existing cross-owner Job → internal `security.authorization_denied` / `job_owner_mismatch` audit, external 404;
- successful administrator cross-owner access → existing admin cross-owner audit remains intact.

This preserves owner-existence concealment while adding the required internal authorization-denial evidence.

### PASS — real HTTP Service Key non-superuser RBAC regression

The previous helper-only test has been replaced with FastAPI/TestClient calls against the actual Service Key routes. Authenticated `data_reader` access to list/create/revoke is asserted as HTTP 403 and the RBAC denial audit is checked for secret-free output.

### PASS — signed Word security-header regression

The signed Word regression now explicitly asserts:

- `Cache-Control: no-store`
- `Referrer-Policy: no-referrer`
- `X-Content-Type-Options: nosniff`

alongside the existing DOCX content type/content disposition behavior.

### PASS — SQLite WAL lock retry

`ReportJobStore._connect()` now retries only SQLite `OperationalError` messages containing `locked`, bounded by the existing `busy_timeout_ms` deadline. Unrelated SQLite failures still propagate. This is a minimal implementation deviation justified by the concurrency failure observed during Codex verification.

### PASS — Review traceability

`docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md` is present again. Its text clearly identifies itself as a reconstructed historical traceability artifact rather than falsely claiming byte-for-byte recovery. Review v3 remains authoritative for the v6.1 completion delta.

### PASS — startup audit disposition

`.codex/decisions.md` records production signing-secret validation as a pre-request process-start failure. The raised startup exception plus service/process logs are the audit channel; application audit storage is not made a prerequisite for starting merely to log a startup failure. Fail-closed startup behavior and secret non-disclosure are preserved.

## Fresh review verification

### Independently executed in this review environment

- `pytest` over security env bootstrap, Service Key CLI/store, Report Job migration/store: **20 passed, 0 failed, 0 errors**.
- Fresh/legacy concurrent Report Job initialization: **5 consecutive rounds passed**; each round initialized both fresh and legacy-v0 databases under 12 concurrent initialization calls and converged to schema version 1 with no migration residue.
- 12-process Service Key mutation: **passed**; unique key IDs, valid JSON, and no raw-key persistence were verified.
- `python -m compileall -q sra_api api tests`: passed.
- AST parse of the reviewed security/concurrency files: passed.
- Canonical production import namespace scan: no forbidden production `sra_api.*` imports were found.
- Original ZIP runtime-artifact scan: no `.env`, `.env.local`, Service Key store, auth store, audit log, `__pycache__`, pytest cache, or `.pyc` artifact was present in the submitted archive.

### Environment limitation

The exact 87-test targeted Phase 0 suite and complete repository suite could not be independently rerun here because this review container lacks the `elasticsearch` package, causing collection errors before those API tests run.

Codex's reported fresh execution evidence is therefore recorded as external implementation evidence, not restated as this reviewer's own test run:

- targeted Phase 0 gate: **87 passed, 0 failed, 0 errors, 3 warnings**;
- full repository suite: **346 passed, 0 failed, 0 errors, 10 warnings**.

The reviewed source contains the changes those tests are intended to exercise, and independent store/migration/concurrency verification above found no contradiction with the report.

## Findings

### Blocking issues

None found in repository implementation.

### Major issues

None found in repository implementation.

### Minor issue — stale `.codex/known_issues.md` historical text is not clearly marked historical

The current `.codex/known_issues.md` still contains an older Phase 0 subsection stating that the substitute verification was `84-test` / `343-test` and that Review v2 was absent / the latest review was v1. Those statements are now stale because:

- current Codex verification is 87 targeted / 346 full;
- Review v2 has been restored;
- Review v3 is the authoritative pre-implementation review.

This does not affect runtime security behavior or the repository security gate, but it can mislead a future Codex session that reads `.codex/known_issues.md`. Correct or explicitly mark that subsection historical in the next documentation-only commit. No Design/Plan version bump is needed.

## Pre-E2E credential status

The submitted ZIP still contains **three real-looking Service Key literals** in `tests_code/test_phase0_api.py`. Under the user-approved Plan v6/v6.1 sequencing this is intentionally preserved only until the mandatory real deployment E2E is completed.

This is **not accepted as final credential hygiene**. After a genuine E2E PASS:

1. create replacement acceptance keys;
2. verify the replacements;
3. revoke the currently exposed keys;
4. verify the revoked keys return 401 on the next protected request;
5. move the smoke harness to environment/ignored local configuration;
6. rerun the relevant repository/security smoke checks.

Do not print or copy the raw values into review, logs, or additional files.

## Deployment acceptance — still pending

Repository tests and mocked downstream Agent seams do not satisfy the final product-chain acceptance requirement.

The operator environment must still prove, without mocking Elasticsearch or the Agent:

1. Service Key authentication succeeds;
2. the Router selects the report/analysis Agent path rather than PURE_LLM/background short-answer behavior;
3. a real Elasticsearch query executes;
4. real source/evidence is retrieved;
5. the long-running Agent continues after retrieval and synthesizes a non-empty report;
6. the chat response contains the expected Word export metadata;
7. the signed Word URL is GET successfully **without Authorization**;
8. the response is a non-empty, structurally valid DOCX.

Use a long read timeout such as `(10, 1800)` and extend to `(10, 3600)` if the legitimate workload requires it.

## Final disposition

### Repository implementation

**PASS — Phase 0 v3 repository security gate is accepted for the reviewed source snapshot.**

### Deployment acceptance

**PENDING — real Elasticsearch / long-running Agent / signed Word E2E has not yet been demonstrated.**

### Design / plan action

- Design v3: unchanged.
- Plan v6.1: repository implementation work complete.
- No Plan v6.2 is needed solely for the minor stale `.codex/known_issues.md` text.
- If the real deployment E2E passes, proceed directly to post-E2E credential hygiene and Phase 0 closure.
- If the real deployment E2E exposes an implementation defect, create the smallest necessary completion delta; do not redesign Phase 0 unless the defect demonstrates a Design v3 contradiction.
