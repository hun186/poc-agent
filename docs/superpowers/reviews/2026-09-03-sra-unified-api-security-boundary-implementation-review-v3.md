# SRA Unified API Security Boundary — Implementation Review v3

## Baseline

- **Actual review baseline:** `poc-agent_20260903-143516.zip` source snapshot supplied by the user. This snapshot is authoritative for this review.
- **Repository / branch / commit:** not independently verifiable from the ZIP because Git metadata is not included. The accompanying Codex execution report states repository `/workspace/poc-agent`, branch `work`, baseline commit `56c6cfababe1b998e379fa672489cd8828d9efaa`, resulting commit `4f8816dcb8f9779a6d0d8f877880b2f3fb8b39c4`; these identifiers are recorded as reported, not independently asserted by this review.
- **Design:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`.
- **Plan:** `docs/superpowers/plans/2026-09-03-sra-unified-api-security-boundary-plan-v6.md`.
- **Requested prior review:** `docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md` is still absent from this actual snapshot. Review v1 is present.

## Verdict

**NOT PASS — repository hardening is substantially complete, but two authorization-denial audit paths still violate Design v3 §14, several Plan v6 regression details remain incomplete, and the mandatory real Elasticsearch → long Agent → report → signed Word deployment E2E has not been executed.**

No Design v4 is required. Design v3 remains valid. The remaining work is a small implementation/test completion delta plus operator-environment E2E acceptance.

## Confirmed completed work to preserve

The supplied source confirms the major Codex delta is present:

- unified authentication-denied and scope-denied audit in `api.security.principal`;
- Service Key create/revoke audit without raw key or digest fields;
- Report Job administrative cross-owner access audit;
- cross-process Service Key mutation locking regression;
- concurrent fresh/legacy Report Job initialization regression;
- canonical signed `download=0|1` behavior;
- duplicate/extra signed query rejection and invalid-Authorization precedence;
- signed document response headers;
- production signing-secret fail-closed and development warning-once tests;
- production CORS origin/header regressions;
- actual-route fast OpenWebUI/scope matrix with downstream Agent mocked only for security-boundary determinism;
- canonical `api.*` production import namespace remains preserved.

The Codex report records 84 targeted tests and a 343-test full repository suite passing in its environment. This review does not reuse those counts as independent evidence; see Verification below.

---

## Major issue 1 — direct authenticated signed-resource scope denial is not audited

**Location**

- `sra_api/security/principal.py`, `require_principal_or_capability()`, current snapshot lines 94–97.

**Problem**

When a valid authenticated principal accesses a document/legacy-Word resource without the required direct-client scope, the shared resolver raises `403 Insufficient scope` directly:

```python
if principal is not None:
    if required_scope not in principal.scopes:
        raise HTTPException(403, "Insufficient scope")
```

Unlike `require_scopes()`, this path does not call the security authorization-denied audit helper.

**Independent reproduction**

A valid service principal with `model:read` was passed to `require_principal_or_capability(... required_scope="document:read" ...)`. Result:

```text
HTTPException 403 Insufficient scope
audit events: []
```

**Why it matters**

Design v3 §14 explicitly requires `authorization denied` audit. The unified resolver is itself part of the approved authorization boundary, so its authenticated-principal denial path must not bypass that audit requirement.

**Required fix**

Before returning 403, emit the same safe authorization-denied event used by `require_scopes()`, including only principal kind/subject and required scope; do not log Authorization, raw credentials, digest, or capability signature.

**Design/Plan impact**

- Design v3: no change.
- Implementation: required.
- Regression: add a test proving the resolver's direct-principal insufficient-scope path emits `security.authorization_denied` and still returns 403.

---

## Major issue 2 — Report Job owner-mismatch denial is concealed as 404 but not authorization-audited

**Location**

- `sra_api/routers/report_jobs.py`, `status()` lines 56–59.
- `sra_api/routers/report_jobs.py`, `download()` lines 63–66.

**Problem**

A principal can possess the correct `report:job:read` or `report:job:download` scope and still be unauthorized because the Job belongs to another owner. Current code correctly returns 404 to conceal Job existence, but records no authorization-denied audit event:

```python
if not job or not _authorized(job, principal):
    raise HTTPException(404, "Report job not found")
```

The code only audits successful administrator cross-owner access.

**Independent reproduction**

A service principal with `report:job:read`, requesting an existing Job owned by a different service principal, produced:

```text
HTTPException 404 Report job not found
audit events: []
```

**Why it matters**

The external 404 concealment is correct and must remain. Internally, however, this is an authorization denial and Design v3 §14 requires authorization-denied auditing. Without it, attempted cross-owner access is invisible in the security audit trail.

**Required fix**

Distinguish internally between:

1. Job does not exist → 404; and
2. Job exists but owner/admin authorization fails → emit a safe `security.authorization_denied` event (for example reason `job_owner_mismatch`, operation read/download, principal identity, Job ID) and still return the same 404 externally.

Do not weaken owner isolation or reveal existence in the HTTP response.

**Design/Plan impact**

- Design v3: no change.
- Implementation: required.
- Regression: add status and download owner-mismatch tests asserting both 404 concealment and audit event.

---

## Major issue 3 — Plan v6's real HTTP non-superuser Service Key administration regression is not actually an HTTP regression

**Location**

- `tests/test_phase0_security_acceptance.py`, `test_non_superuser_cannot_administer_service_keys()`, current snapshot lines 99–109.

**Problem**

Plan v6 Task 1 requires real Service Key HTTP administration/RBAC regressions, including `non-superuser Service Key administration → 403`.

The current test constructs a FastAPI app but then clears dependency overrides and calls a newly constructed `require_role(...)` dependency directly. It never sends an authenticated non-superuser HTTP request to `/v1/auth/service-keys`.

**Actual result / risk**

The production route currently visibly uses `Depends(require_superuser)`, so no current bypass was found. However, the tracked regression would still pass if the Service Key route were later miswired to the wrong dependency, because it tests the helper instead of the route contract.

**Required fix**

Use the canonical Editor-auth test seam to authenticate/override `current_user` as a `data_reader` (or equivalent insufficient role), call the actual create/list/revoke HTTP endpoint, and assert 403 plus safe authz audit behavior.

**Design/Plan impact**

- Design v3: no change.
- Production code: likely no change unless the real route test exposes a defect.
- Test gate: required Plan v6 completion.

---

## Minor issue 1 — signed legacy Word security headers are implemented but not explicitly asserted

**Location**

- Implementation: `sra_api/routers/export.py` sets `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Content-Type-Options: nosniff`.
- `tests/test_phase0_security_acceptance.py::test_successful_signed_resources_have_security_headers()` asserts the three headers only for signed detail/fulltext.
- `tests/test_api_security_boundaries.py::test_openwebui_can_download_word_without_editor_token()` validates Word status/content type/content disposition but not those three security headers.

**Problem**

Plan v6 Task 3A explicitly requires successful signed detail/fulltext/**Word** responses to assert all security headers.

**Required fix**

Extend the existing signed Word route regression with the three header assertions. No production code change appears necessary.

---

## Minor issue 2 — Implementation Review v2 artifact is still absent from the repository snapshot

**Location**

Expected:

`docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md`

Actual snapshot contains only Review v1.

**Impact**

No functional defect was found from this absence because Plan v6 carried forward Review v2's completion requirements and Codex implemented most of them. It remains a traceability/process defect and should be restored before Phase 0 is closed.

---

## Minor issue 3 — startup signing-secret failure is fail-closed but has no explicit security-audit event

**Location**

- `sra_api/security/signed_urls.py::validate_signing_config()` / `_secret()`.
- `sra_api/main.py` lifespan startup.

**Observation**

Production missing/weak signing secret correctly raises `RuntimeError`, but no application audit record is emitted for that configuration failure. Design v3 §14 lists `security configuration failure at startup where applicable` among audit events.

**Assessment**

This does not weaken fail-closed startup behavior. Treat as a small Design-completeness item: either add a safe startup audit before re-raising or explicitly document why process/service logs are the authoritative startup audit channel for this pre-start condition.

---

## Deployment blocker — mandatory real ES / long Agent / Word E2E remains NOT EXECUTED

This remains a blocking acceptance condition exactly as Plan v6 intended. Repository tests, even a 343-test green suite, cannot substitute for the operator-environment proof that a representative report request actually performs:

```text
real Service Key authentication
→ report/analysis routing
→ real Elasticsearch retrieval
→ actual source/evidence return
→ long-running report Agent
→ synthesized report
→ word_export.url
→ signed GET without Authorization
→ valid non-empty DOCX
```

The current snapshot still contains the operator's existing acceptance keys in `tests_code/test_phase0_api.py`. Per the user-approved Plan v6 sequencing, do not rotate or replace them before the real E2E succeeds; after E2E, rotate/revoke them and remove literal credentials from the harness before final Phase 0 closure.

---

## Verification performed by Review v3

Fresh checks in the review environment:

1. `python -m compileall -q sra_api api tests` — completed successfully (one pre-existing `SyntaxWarning` in a docx table presenter was emitted during a broader scan; compile completed).
2. `PYTHONPATH=. pytest -q tests/test_report_job_store.py tests/test_report_job_migration_v1.py tests/test_service_key_store.py tests/test_service_key_cli.py tests/test_security_env_bootstrap.py --tb=short` — **20 passed, 0 failed, 0 errors**.
3. Custom concurrent Report Job initialization probe:
   - fresh DB: canonical version 1, no migration residue, canonical partial index present;
   - legacy v0 DB: canonical version 1, no migration residue, canonical partial index present.
4. Custom 24-process Service Key mutation probe:
   - 24 persisted keys;
   - 24 unique key IDs;
   - 0 raw-key persistence leaks.
5. Production canonical-namespace scan: no `from/import sra_api...` imports found under production `sra_api/*.py`.
6. Current snapshot scan confirms the pre-E2E smoke harness still contains three real-looking Service Key literals; this is intentionally preserved under Plan v6 until real E2E, not accepted as final hygiene.

Environment limitation:

- The review environment does not provide `elasticsearch` / `smolagents`, and package installation cannot reach the package index. Therefore the 84-test targeted suite and 343-test full suite could not be independently rerun here. Codex's reported counts are recorded but not treated as fresh Review v3 evidence.

## Phase 0 status after Review v3

### Repository hardening completed or substantially complete

- unified principal and scope protection;
- Service Key store/CLI/API skeleton and cross-process persistence locking;
- owner-aware Report Job persistence and migration hardening;
- signed capability exact binding and query fail-closed behavior;
- CORS and production signing-secret behavior;
- OpenWebUI least-privilege fast route matrix;
- security audit for many major denial/admin paths.

### Repository gate still open

1. audit direct-principal scope denial in `require_principal_or_capability`;
2. audit Report Job owner-mismatch denial while preserving external 404;
3. replace the direct dependency-only non-superuser test with an actual HTTP Service Key admin regression;
4. assert signed legacy Word security headers;
5. restore Review v2 artifact;
6. resolve/document startup configuration failure audit treatment.

### Deployment gate still open

- real ES → long report Agent → signed Word E2E;
- post-E2E acceptance-key rotation and smoke-harness secret cleanup.

## Version decision

- **Design v3 remains authoritative.**
- **No Design v4 is required.**
- The next Codex work should be a small Plan v6 completion delta, not a redesign or a replay of already-passing Phase 0 hardening.
