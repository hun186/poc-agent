# SRA Unified API Security Boundary Final Acceptance Implementation Plan — v6

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Phase 0 v3 security gaps and prove the deployed product through a mandatory real Elasticsearch → long-running Agent → report → signed Word end-to-end acceptance path before rotating or changing the currently working smoke-test Service Keys.

**Architecture:** Preserve Design v3 and all completed Plan v4/v5 hardening. Fast authentication/authorization regressions remain deterministic and may mock downstream Agent execution, but they are not the final acceptance test. The final Phase 0 deployment gate must exercise the real configured SRA API, real Service Key authentication, actual routing into the long-running report Agent, real Elasticsearch retrieval, final report synthesis, `word_export` metadata, and signed DOCX download. Existing working test credentials must remain unchanged until this live E2E gate has actually passed.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLite, Elasticsearch integration, existing SRA Agent/report pipeline, pytest/TestClient, live `requests` smoke harness.

**Spec:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`

**Review:** `docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md`

**Supersedes:** `docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v5.md` for remaining work and acceptance sequencing only. Completed v4/v5 implementation remains baseline and must not be rebuilt.

## Baseline

- Source snapshot used for this update: `poc-agent_20260902-215349.zip` plus the user's explicit acceptance clarification on 2026-09-03.
- Prior Codex implementation baseline reported: repository `/workspace/poc-agent`, branch `work`, commit `0c9379b54`; actual Git identity must be re-read at execution time.
- Design version: v3.
- Review version: Implementation Review v2.
- Plan version: v6.

## What changed from Plan v5

1. Real long-running report execution is no longer optional deployment smoke; it is a **mandatory Phase 0 final deployment acceptance gate**.
2. That gate must use the real configured Elasticsearch path and the real report Agent. A mocked Agent/ES response cannot satisfy it.
3. Existing working smoke/E2E Service Keys must **not be revoked, rotated, replaced, removed, or rewritten before the mandatory real E2E gate passes**.
4. Secret-hygiene cleanup of those already-exposed test credentials moves **after** successful live E2E. Do not copy their values into new files, logs, commits, docs, audit records, or Codex reports.
5. Fast scope/RBAC tests still mock downstream Agent execution because their purpose is security isolation, not workload validation.
6. Long-request read timeout must be configurable and large enough for the actual report workload (default 1800 seconds; 3600 seconds allowed for acceptance when operationally necessary).

## Global Constraints

- Actual repository source at execution time overrides stale paths/line numbers, but not Design v3.
- Do not redesign principal/scopes, Service Key format/store, signed capability model, owner-aware Job schema, Report Job migration ordering, CORS architecture, Agent routing, or ES retrieval unless an actual blocking defect requires the minimum necessary change.
- Do not weaken authentication, authorization, owner isolation, audit, transaction, rollback, validation, fail-closed behavior, secret handling, or existing Editor RBAC.
- Do not add Batch Scheduler, GUI/Dashboard, Redis/Celery/PostgreSQL, OIDC/OAuth, rate limiting, or unrelated Agent/retrieval features.
- **Do not change the currently working live test Service Keys before Task 5 succeeds.** This includes revoke, rotate, replace, delete, or converting the live harness to different credentials merely for hygiene.
- Do not print or duplicate those credentials anywhere new. Treat them as operator-owned acceptance credentials until Task 5 is complete.
- Fast automated security tests may mock the downstream Agent seam. **The mandatory Task 5 live E2E must not mock Elasticsearch, routing, Agent execution, report generation, or Word export.**
- A long-running Agent timeout is a workload/E2E result, not an authentication result. Do not misclassify timeout as 401/403.

---

## Task 0: Re-baseline actual repository and preserve completed hardening

**Files:**
- Read: `AGENTS.md`
- Read: `.codex/memory.md`
- Read: `.codex/backlog.md`
- Read: Design v3, Review v2, Plan v6
- Inspect: current security/router/store/report/Agent/smoke files

**Interfaces:**
- Consumes: actual Git repository state.
- Produces: exact baseline and remaining-gap matrix.

- [ ] **Step 1: Record repository identity**

```bash
pwd
git branch --show-current
git rev-parse HEAD
git status --short
```

Do not invent remote/repository metadata.

- [ ] **Step 2: Confirm completed v4/v5 behavior before edits**

Verify current source still contains the approved behavior for:

```text
env bootstrap ordering
CLI bootstrap before ServiceKeyStore construction
require_principal_or_capability
signed response security headers
Service Key expires_at validation
Report Job v0→v1 validation/rollback hardening
PRODUCTION_ENVS reuse
```

Do not reimplement passing behavior.

- [ ] **Step 3: Identify the actual live E2E route and evidence points**

Read the current `/v1/chat/completions` implementation and downstream Agent/report code. Record the actual fields/log/context that can prove:

```text
request passed authn/authz
router selected the report/analysis Agent path
Elasticsearch retrieval actually executed
retrieval returned source/evidence data
long-running Agent completed
final report content was produced
word_export metadata was attached
signed DOCX was downloadable
```

Use current source names; do not invent a new route marker if equivalent evidence already exists.

---

## Task 1: Finish unified audit and real Service Key HTTP administration regressions

**Files:**
- Modify only as needed: `sra_api/security/principal.py`
- Modify only as needed: `sra_api/routers/service_keys.py`
- Modify only as needed: `sra_api/routers/report_jobs.py`
- Reuse: existing audit sink such as `sra_api/services/editor_audit.py`
- Extend/create tests according to current repository structure.

**Required tracked behaviors:**

```text
authentication denied audit
authorization denied audit
service-key created audit
service-key revoked audit
admin cross-owner Report Job access audit
superuser create/list/revoke Service Key over HTTP
non-superuser Service Key administration → 403
service-key principal cannot satisfy Editor superuser RBAC
unknown scope → validation failure
revoked key next protected request → 401
raw key appears only in create response
list/revoke/audit/logs do not expose raw key or token_digest
```

- [ ] Write failing regressions first.
- [ ] Implement the minimum missing behavior.
- [ ] Run the targeted audit/admin tests and report exact counts.

---

## Task 2: Finish cross-process Service Key and concurrent Report Job initialization regressions

**Files:**
- Prefer tests first: `tests/test_security_concurrency.py` or current equivalent.
- Extend Report Job migration/store tests.
- Modify production locking/SQLite code only if the new regression actually fails.

**Required proof:**

```text
multiple processes mutate one Service Key store without lost update
JSON remains valid
key_id values remain unique
no raw key is persisted
concurrent fresh ReportJobStore initialization converges to canonical v1
concurrent supported legacy v0 initialization/migration preserves rows
no report_jobs_new/report_jobs_old residue remains
partial owner-scoped uniqueness remains canonical
```

Preserve the approved migration ordering.

---

## Task 3: Complete capability, startup/CORS, and least-privilege automated regressions

**Files:**
- Extend/create the current capability/startup/CORS/auth test modules.
- Modify production source only if a failing regression proves a real defect.

### 3A. Signed capability adversarial matrix

Prove fail-closed behavior for:

```text
duplicate sig / format / download / text_layer / session_id / turn_id
unsupported extra query key
noncanonical signed download boolean
invalid Authorization + valid sig → 401, no capability fallback
cross-doc/cross-resource/cross-representation substitution
legacy Word session/turn substitution
capability validation before resource lookup
```

Successful signed detail/fulltext/Word responses must assert:

```text
Cache-Control: no-store
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```

### 3B. Fast scope/OpenWebUI least-privilege matrix

These tests are intentionally deterministic and may mock the downstream Agent execution seam:

```text
no key models → 401
invalid key models → 401
model:read models → 200
model:invoke-only models → 403
model:read-only chat → 403
OpenWebUI model:read+model:invoke passes models/chat security boundary
OpenWebUI key cannot POST report jobs
report/batch key without model:invoke cannot chat
service key cannot enter Editor admin
spoofed conversation/session headers are not authentication
revoked key next protected request → 401
```

**Important:** A mocked `execute_agent_turn` (or current equivalent) proves only security routing. It does **not** satisfy Task 5.

### 3C. Startup/CORS matrix

Prove:

```text
production missing/weak SRA_SIGNED_URL_SECRET fails closed
valid >=32-byte production secret passes
non-production fallback warning occurs once and contains no secret
production empty CORS origins is not wildcard
configured preflight permits required OpenWebUI/SRA headers
unconfigured origin is not granted configured policy
```

---

## Task 4: Run automated repository gate before live workload acceptance

Run fresh targeted suites, affected regression suites, full pytest, compileall, `git diff --check`, namespace guards, audit/Authorization/digest leak scans, and tracked runtime-secret/cache artifact scans.

### Credential handling at this stage

- Do **not** fail this pre-E2E gate merely because the already-existing operator smoke harness still contains the currently working acceptance credentials.
- Do fail if implementation work creates **new copies** of those values in other source/docs/logs/tests/memory.
- Do not rotate/revoke/replace them yet.
- Record explicitly: `live acceptance credentials intentionally preserved pending Task 5`.

No Phase 0 final PASS declaration is allowed at Task 4.

---

## Task 5: Mandatory real Elasticsearch → long Agent → report → signed Word E2E acceptance

**This task is mandatory for Phase 0 deployment acceptance and cannot be replaced by mocks.**

**Files:**
- Use the current live smoke harness, e.g. `tests_code/test_phase0_api.py`.
- Do not change its working Service Keys before this task passes.
- Source changes are allowed only if the live test exposes a real product defect.

### Step 1: Run the fast live security smoke first

Against the configured running SRA API, verify at minimum:

```text
GET /healthz without key → 200
GET /v1/models without key → 401
GET /v1/models invalid key → 401
GET /v1/models read-only key → 200
POST /v1/chat/completions read-only key → 403
POST /v1/report/jobs OpenWebUI key → 403
```

### Step 2: Run a short/background prompt to observe the non-report path when supported

Use a lightweight prompt that should not require full report generation. Record the actual route/evidence available from current implementation. This is a routing sanity check only.

### Step 3: Run the real long report prompt

Use a representative operator-approved report prompt that is expected to trigger the actual report/analysis Agent and real Elasticsearch retrieval.

Use a configurable timeout, for example:

```python
timeout=(10, int(os.environ.get("SRA_SMOKE_LONG_READ_TIMEOUT", "1800")))
```

Operationally, `3600` seconds is allowed if the real workload legitimately exceeds 30 minutes.

### Step 4: Prove the request really used the product's core path

Do not accept `HTTP 200` alone. Capture evidence from current implementation that demonstrates all applicable items:

```text
report/analysis Agent route selected
real Elasticsearch query/retrieval occurred
retrieval produced actual source/evidence data
Agent/report pipeline continued after retrieval
final synthesized report content returned
```

If the current product exposes route/context/source metadata, assert it. If evidence is only available from existing server/Agent/ES logs, record the exact observed evidence. Do not add a fake marker solely to make the test pass unless observability is genuinely missing and the minimum safe instrumentation is justified.

### Step 5: Validate chat completion result

Require:

```text
HTTP 200
choices[0].message.content is non-empty
response is not merely a short background-LLM answer when the prompt requires report Agent execution
expected retrieval/source/report context is present according to current API contract
choices[0].message.context.word_export.url exists
```

### Step 6: Download the real signed Word artifact

GET `word_export.url` **without** an Authorization header and verify:

```text
HTTP 200
DOCX-compatible Content-Type
non-empty content
ZIP/DOCX structure is valid
report document can be opened/parsed by an appropriate DOCX reader or ZIP validation
```

Save the file to the operator-selected output path.

### Step 7: Classify long timeout correctly

If the client read timeout expires after auth has passed and the backend is still working:

```text
authentication/authorization: passed if separately evidenced
real E2E completion: NOT OBSERVED / FAIL for acceptance
```

Do not report the timeout as an auth failure and do not declare deployment acceptance PASS.

### Step 8: Mandatory acceptance result

Task 5 is PASS only if the real ES + Agent + report + Word chain completes and the evidence above is satisfied.

If Codex cannot access the configured SRA API/ES/test credentials, report `NOT EXECUTED`. In that case:

- do not claim Phase 0 deployment acceptance;
- do not revoke/rotate/replace the current test credentials;
- leave Task 6 pending for the operator after real E2E evidence is provided.

---

## Task 6: Post-E2E credential hygiene and smoke-harness cleanup

**Precondition:** Task 5 must have passed in the configured environment.

Only after that:

1. Treat the previously exposed test Service Keys as compromised test credentials.
2. Operator revokes/rotates them in the actual Service Key store.
3. Update `tests_code/test_phase0_api.py` to read replacement keys from environment variables or another ignored local configuration source.
4. Never commit replacement key values.
5. Add/enable the repository real-looking `sra_sk_...` literal guard.
6. Verify old keys now return `401` on the next protected request.
7. Verify replacement keys still pass the fast live smoke.

If Task 5 has not passed, **do not execute Task 6** merely to satisfy secret-hygiene style rules.

---

## Task 7: Final Phase 0 repository + deployment gate

After Tasks 1–6 are complete:

### Repository gate

Fresh-run:

```text
all Phase 0 targeted tests
all affected API/Job regressions
full `pytest tests -q --tb=short`
compileall
git diff --check
canonical namespace guard
Authorization/raw-key/token_digest/audit leak scan
real-looking Service Key literal scan
tracked runtime-secret/cache artifact scan
git status --short
```

All required modules must exist or be replaced by clearly equivalent current modules with requirement coverage documented.

### Deployment gate

Require recorded Task 5 evidence and post-E2E Task 6 key-rotation result.

Only then may Codex state both:

```text
Phase 0 v3 repository security gate passed after Plan v6 completion.
Phase 0 v3 deployment acceptance smoke passed with real Elasticsearch retrieval, long-running report Agent execution, and signed Word export.
```

If Task 5 was NOT EXECUTED or failed, neither combined Phase 0 completion declaration is allowed. Report the exact pending condition instead.

## Required Execution Report

- Repository
- Branch
- Baseline commit
- Resulting commit, if any
- Design version: v3
- Review version: v2
- Plan version: v6
- Changed files
- Behavior changes
- Tests executed
- Exact test pass/fail/error/warning counts
- Fast live security smoke result
- Real long Agent E2E result
- Evidence that Elasticsearch retrieval actually occurred
- Evidence that report Agent path actually executed
- Word export/download result
- Credential handling status: preserved pending E2E / rotated after E2E
- Deviations from Plan v6
- Remaining issues / risks
