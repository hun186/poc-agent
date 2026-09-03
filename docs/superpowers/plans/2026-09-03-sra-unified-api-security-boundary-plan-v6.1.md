# SRA Unified API Security Boundary — Phase 0 Completion Plan v6.1

> **For agentic workers:** Execute this plan task-by-task against the actual repository. Preserve Design v3. This is a completion delta, not a redesign.

**Goal:** Close the remaining repository-security gaps identified by Implementation Review v3, preserve all completed Phase 0 hardening, and reach the final real Elasticsearch → long-running report Agent → signed Word deployment acceptance gate.

**Architecture:** Keep the existing unified principal/scope boundary, Service Key store, signed-capability resolver, Report Job ownership model, CORS/startup policy, and migration implementation unchanged except where Review v3 identifies a concrete gap. Add audit coverage at the two remaining authorization-denial seams, make the Service Key non-superuser regression exercise the real HTTP route, complete signed Word header assertions, restore review traceability, then run the real product-chain E2E without mocking Elasticsearch or the Agent.

**Tech Stack:** Python, FastAPI, pytest, SQLite, existing Service Key JSON store, Elasticsearch-backed SRA Agent pipeline.

**Spec:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`

**Authoritative Review:** `docs/superpowers/reviews/2026-09-03-sra-unified-api-security-boundary-implementation-review-v3.md`

**Supersedes:** Plan v6 **only for remaining incomplete work**. All Plan v6 items already implemented and verified must be preserved and not reworked.

## Baseline

- **Actual source snapshot used to write this plan:** `poc-agent_20260903-143516.zip`.
- **Repository / branch:** accompanying Codex report states `/workspace/poc-agent`, branch `work`; verify actual values before editing.
- **Reported prior resulting commit:** `4f8816dcb8f9779a6d0d8f877880b2f3fb8b39c4`; verify actual HEAD rather than assuming this identifier.
- **Design:** v3.
- **Prior Plan:** v6.
- **Current Review:** v3.
- **Review v2:** historical traceability artifact; restore it if absent, but **do not block execution on reading it**. Review v3 is authoritative for this delta.

## Global Constraints

- Actual repository source is authoritative if paths moved; preserve behavior required by Design v3.
- Do not create Design v4 unless the actual source reveals a blocking architecture contradiction in Design v3.
- Do not reimplement completed env bootstrap, Service Key storage, signed-capability validation, CORS hardening, Report Job migration, concurrency locking, or existing security headers.
- Preserve fail-closed authentication/authorization, owner isolation, 404 concealment for cross-owner Report Jobs, transaction/rollback guarantees, validation, and secret handling.
- Never log or newly copy Authorization headers, raw Service Keys, `token_digest`, signed capability signatures, or other credentials.
- Existing working live acceptance Service Keys must remain unchanged until the mandatory real E2E passes. Do not revoke, rotate, replace, delete, or migrate them before that gate.
- Fast security regression tests may mock only the downstream Agent seam. The final deployment E2E must use the real Router, real Elasticsearch retrieval, real long-running Agent, real report synthesis, and real signed Word download.
- A dependency/collection failure is not a pass.

---

## Task 0 — Re-baseline and restore review traceability

**Files:**
- Restore if absent: `docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md`
- Add/preserve: `docs/superpowers/reviews/2026-09-03-sra-unified-api-security-boundary-implementation-review-v3.md`
- Read: `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`
- Read: `docs/superpowers/plans/2026-09-03-sra-unified-api-security-boundary-plan-v6.md`

**Interfaces:**
- Consumes: actual Git repository and current source.
- Produces: recorded Repository, Branch, HEAD commit, git status, and an execution baseline tied to Design v3 / Review v3 / Plan v6.1.

- [ ] **Step 1: Record the actual baseline**

Run:

```bash
pwd
git branch --show-current
git rev-parse HEAD
git status --short
git remote -v || true
```

Do not invent a repository URL if no remote exists.

- [ ] **Step 2: Confirm Review v3 findings against current source before editing**

Inspect at minimum:

```text
sra_api/security/principal.py::require_principal_or_capability
sra_api/routers/report_jobs.py::status
sra_api/routers/report_jobs.py::download
tests/test_phase0_security_acceptance.py::test_non_superuser_cannot_administer_service_keys
tests/test_api_security_boundaries.py::test_openwebui_can_download_word_without_editor_token
```

If the current source already fixed a finding, do not reapply it; verify with the required regression instead.

- [ ] **Step 3: Restore review artifacts without changing historical content**

Place Review v2 and Review v3 under `docs/superpowers/reviews/`. Do not rewrite Review v2 to match current code; it is historical evidence.

- [ ] **Step 4: Commit traceability with the implementation delta or as a dedicated docs commit**

No functional behavior should change in this step.

---

## Task 1 — Audit direct authenticated signed-resource scope denial

**Files:**
- Modify: `sra_api/security/principal.py`
- Test: `tests/test_phase0_security_acceptance.py`

**Interfaces:**
- Consumes: `_audit_denied()`, `AuthPrincipal`, `require_principal_or_capability()`.
- Produces: a `security.authorization_denied` event for a valid principal lacking the required direct-client scope while preserving HTTP 403.

- [ ] **Step 1: Add the failing regression**

Add a test equivalent to:

```python
def test_direct_principal_signed_resource_scope_denial_is_audited(monkeypatch):
    events = []
    monkeypatch.setattr("api.security.principal.append_audit_event", events.append)
    principal = AuthPrincipal(
        "service",
        "reader",
        None,
        frozenset({"model:read"}),
        "key-id",
    )
    request = SimpleNamespace(query_params={})

    with pytest.raises(Exception) as denied:
        require_principal_or_capability(
            request,
            principal,
            required_scope="document:read",
            resource_type="doc_detail",
            binding={"doc_id": "doc"},
            allowed_query_keys=set(),
        )

    assert denied.value.status_code == 403
    assert events == [{
        "action": "security.authorization_denied",
        "reason": "insufficient_scope",
        "principal_kind": "service",
        "subject": "reader",
        "required_scopes": ["document:read"],
    }]
```

Use the actual request fixture/type if the current source makes that cleaner. The regression must exercise `require_principal_or_capability()` itself.

- [ ] **Step 2: Run the regression and confirm RED**

```bash
PYTHONPATH=. pytest -q tests/test_phase0_security_acceptance.py -k direct_principal_signed_resource_scope_denial --tb=short
```

Expected before the fix: HTTP 403 occurs, but the expected audit event is absent.

- [ ] **Step 3: Implement the minimal audit fix**

In the authenticated-principal branch, before raising 403, call the existing safe helper:

```python
_audit_denied(
    "security.authorization_denied",
    reason="insufficient_scope",
    principal=principal,
    required_scopes={required_scope},
)
raise HTTPException(403, "Insufficient scope")
```

Do not change capability fallback behavior or HTTP status.

- [ ] **Step 4: Re-run targeted security tests**

```bash
PYTHONPATH=. pytest -q tests/test_phase0_security_acceptance.py tests/test_signed_resource_urls.py tests/test_api_security_boundaries.py --tb=short
```

- [ ] **Step 5: Commit**

Suggested message:

```text
fix: audit signed-resource scope denials
```

---

## Task 2 — Audit Report Job owner mismatch while preserving 404 concealment

**Files:**
- Modify: `sra_api/routers/report_jobs.py`
- Test: `tests/test_phase0_security_acceptance.py`
- Test if useful: `tests/test_job_authorization.py`

**Interfaces:**
- Consumes: `_authorized()`, `append_audit_event()`, Report Job owner fields, `AuthPrincipal`.
- Produces: internal `security.authorization_denied` audit for existing cross-owner Job access while the external response remains exactly 404.

- [ ] **Step 1: Add failing status and download regressions**

Create an existing Job owned by a different non-admin principal. For status and download separately, assert:

```python
assert denied.value.status_code == 404
assert events == [{
    "action": "security.authorization_denied",
    "reason": "job_owner_mismatch",
    "principal_kind": "service",
    "subject": "requester",
    "job_id": "job-1",
    "operation": "read",  # or "download"
}]
```

The request principal must already possess `report:job:read` or `report:job:download`; this test targets owner authorization, not scope authorization.

Also assert a nonexistent Job still returns 404 without falsely claiming owner mismatch for a Job that was never found.

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=. pytest -q tests/test_phase0_security_acceptance.py -k 'owner_mismatch' --tb=short
```

Expected before the fix: 404 is returned, but no owner-mismatch audit event exists.

- [ ] **Step 3: Implement a focused helper**

Use a local safe helper such as:

```python
def _audit_owner_mismatch(job, principal, operation):
    append_audit_event({
        "action": "security.authorization_denied",
        "reason": "job_owner_mismatch",
        "principal_kind": principal.kind,
        "subject": principal.subject,
        "job_id": job.job_id,
        "operation": operation,
    })
```

Then structure each route as:

```python
job = _store(request).get(job_id)
if not job:
    raise HTTPException(404, "Report job not found")
if not _authorized(job, principal):
    _audit_owner_mismatch(job, principal, "read")  # or download
    raise HTTPException(404, "Report job not found")
```

Keep successful admin cross-owner audit behavior unchanged.

- [ ] **Step 4: Run Report Job authorization/lifecycle regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/test_phase0_security_acceptance.py \
  tests/test_job_authorization.py \
  tests/test_report_jobs_api.py \
  tests/test_report_jobs_lifecycle.py \
  tests/test_report_job_store.py \
  --tb=short
```

- [ ] **Step 5: Commit**

Suggested message:

```text
fix: audit report job owner denials
```

---

## Task 3 — Make non-superuser Service Key administration a real HTTP regression

**Files:**
- Modify: `tests/test_phase0_security_acceptance.py`
- Production code: only modify `sra_api/routers/service_keys.py` or `sra_api/routers/editor_dependencies.py` if the real HTTP regression exposes an actual defect.

**Interfaces:**
- Consumes: `service_keys.router`, `editor_dependencies.current_user`, `require_superuser`, `AuthUser`.
- Produces: route-level proof that a valid authenticated non-superuser cannot create, list, or revoke Service Keys.

- [ ] **Step 1: Replace the helper-only test with real HTTP requests**

Use the canonical FastAPI dependency override seam:

```python
from api.routers import editor_dependencies

app = FastAPI()
app.include_router(service_keys.router)
app.dependency_overrides[editor_dependencies.current_user] = lambda: AuthUser(
    "reader", "data_reader", "active"
)
client = TestClient(app)

assert client.get("/v1/auth/service-keys").status_code == 403
assert client.post(
    "/v1/auth/service-keys",
    json={"name": "denied", "scopes": ["model:read"]},
).status_code == 403
assert client.post("/v1/auth/service-keys/nonexistent/revoke").status_code == 403
```

Capture the existing Editor RBAC audit sink and assert denial events contain no credential material. The test must go through the actual route dependency graph.

- [ ] **Step 2: Run the real HTTP test**

```bash
PYTHONPATH=. pytest -q tests/test_phase0_security_acceptance.py -k non_superuser --tb=short
```

If it passes without production changes, do not refactor the route.

- [ ] **Step 3: Re-run Service Key administration coverage**

```bash
PYTHONPATH=. pytest -q \
  tests/test_phase0_security_acceptance.py \
  tests/test_service_key_api.py \
  tests/test_service_key_store.py \
  tests/test_service_key_cli.py \
  --tb=short
```

- [ ] **Step 4: Commit**

Suggested message:

```text
test: exercise service key admin RBAC over HTTP
```

---

## Task 4 — Complete signed Word response regression and startup-audit disposition

**Files:**
- Modify: `tests/test_api_security_boundaries.py` or `tests/test_phase0_security_acceptance.py`
- Review/document: `.codex/decisions.md` and/or security documentation only for the startup-audit disposition.
- Production code: do not change `sra_api/routers/export.py` unless the test exposes missing headers.

**Interfaces:**
- Consumes: legacy signed Word route and existing fail-closed signing-secret startup behavior.
- Produces: explicit regression coverage for signed Word security headers and a recorded resolution for pre-start configuration-failure auditing.

- [ ] **Step 1: Assert all three security headers on successful signed Word download**

Extend the existing Word test to assert:

```python
assert response.headers["cache-control"] == "no-store"
assert response.headers["referrer-policy"] == "no-referrer"
assert response.headers["x-content-type-options"] == "nosniff"
```

Retain existing DOCX content-type/content-disposition assertions.

- [ ] **Step 2: Run Word/capability tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_api_security_boundaries.py \
  tests/test_phase0_security_acceptance.py \
  tests/test_signed_resource_urls.py \
  --tb=short
```

- [ ] **Step 3: Record startup security-audit disposition without weakening fail-closed startup**

Keep the existing `RuntimeError` fail-closed behavior for missing/weak production `SRA_SIGNED_URL_SECRET`.

Because this failure occurs during application startup before normal request handling, record one explicit decision in `.codex/decisions.md`:

```text
Production signing-secret validation failures are process-start failures. The raised startup exception and service/process logs are the authoritative audit channel for this pre-request condition; the application audit store is not required to initialize merely to record a startup failure.
```

Do not add a new audit-store dependency to startup solely for this item. Do not log the secret value.

- [ ] **Step 4: Commit**

Suggested message:

```text
test: complete signed word security regression
```

---

## Task 5 — Fresh repository security gate

**Files:**
- No intended production changes.
- Update `.codex/memory.md`, `.codex/backlog.md`, `.codex/known_issues.md` only with results that were actually observed.

**Interfaces:**
- Consumes: Tasks 0–4.
- Produces: fresh repository verification evidence before any live E2E claim.

- [ ] **Step 1: Run the Phase 0 targeted gate**

```bash
PYTHONPATH=. pytest -q \
  tests/test_phase0_security_acceptance.py \
  tests/test_agent_api_auth.py \
  tests/test_unified_principal.py \
  tests/test_job_authorization.py \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_service_key_cli.py \
  tests/test_security_env_bootstrap.py \
  tests/test_signed_resource_urls.py \
  tests/test_api_security_boundaries.py \
  tests/test_report_job_migration_v1.py \
  tests/test_report_job_store.py \
  tests/test_report_jobs_api.py \
  tests/test_report_jobs_lifecycle.py \
  tests/test_report_job_worker.py \
  tests/test_security_cors.py \
  --tb=short
```

Record exact pass/fail/error/warning counts.

- [ ] **Step 2: Run full repository tests**

```bash
PYTHONPATH=. pytest tests -q --tb=short
```

A collection/import/dependency error is a failure of this gate.

- [ ] **Step 3: Run static/syntax checks**

```bash
python -m compileall -q sra_api api tests
git diff --check
rg -n '(^|[[:space:]])(from|import)[[:space:]]+sra_api' sra_api --glob '*.py' || true
git ls-files | rg '(^|/)(\.env$|\.env\.local$|\.sra_service_keys|\.auth_users|login_audit|sra-auth-log|__pycache__|\.pytest_cache|\.pyc$)' || true
```

Run focused scans for newly added Authorization/raw key/`token_digest` leakage. Do not print any raw credential in the execution report.

- [ ] **Step 4: Stop if any Blocking/Major repository finding remains**

Do not proceed to a deployment PASS declaration until the repository gate is clean.

---

## Task 6 — Mandatory real Elasticsearch → long Agent → signed Word deployment E2E

**Files:**
- Use the existing operator smoke harness (`tests_code/test_phase0_api.py` or current equivalent) without copying its credentials elsewhere.
- Do not commit newly exposed credentials.

**Interfaces:**
- Consumes: a running SRA API, existing working acceptance Service Key, actual Router, actual Elasticsearch, actual Agent pipeline, signed Word export.
- Produces: operator-environment acceptance evidence for the real product chain.

- [ ] **Step 1: Preserve existing working acceptance credentials**

Before E2E PASS:

```text
DO NOT revoke
DO NOT rotate
DO NOT replace
DO NOT delete
DO NOT copy raw key values into new files/logs/reports
```

- [ ] **Step 2: Run fast live security smoke against the real API**

Verify:

```text
healthz without key                 -> 200
models without key                  -> 401
models invalid key                  -> 401
models read-only key                -> 200
chat read-only key                  -> 403
report jobs with OpenWebUI key      -> 403
```

If the execution environment proxy intercepts all requests, classify as **NOT EXECUTED**, not application failure.

- [ ] **Step 3: Run a representative long report request with a long read timeout**

Use the actual report/analysis prompt and a configurable read timeout, normally:

```python
timeout=(10, 1800)
```

If the real workload legitimately exceeds 30 minutes, use up to:

```python
timeout=(10, 3600)
```

Do not replace this test with a mocked Agent or mocked Elasticsearch call.

- [ ] **Step 4: Prove the request used the real report path**

Collect existing, non-secret evidence that demonstrates all of:

```text
Router selected report/analysis Agent rather than PURE_LLM/background short-answer path
actual Elasticsearch query/retrieval occurred
retrieval returned source/evidence
Agent continued after retrieval and synthesized a final report
final report content is non-empty
```

Prefer existing route/context/trace metadata. If server/Agent/ES logs are the only available evidence, record concrete non-secret log evidence without credentials.

- [ ] **Step 5: Verify and download signed Word**

From the actual chat response, resolve the current `word_export.url` contract. GET the signed URL **without Authorization** and assert:

```text
HTTP 200
DOCX MIME type
non-empty response
valid ZIP/DOCX structure
artifact can be opened/parsed
```

- [ ] **Step 6: Classify result precisely**

- Auth accepted but Agent exceeds timeout: auth boundary may be recorded as pass, but real E2E is `FAIL/NOT COMPLETED`.
- Environment cannot reach the private API/ES: `NOT EXECUTED`.
- Only a genuine full chain result may be `PASS`.

---

## Task 7 — Post-E2E credential hygiene and final declaration

**Files:**
- Modify smoke harness/config only after real E2E PASS.
- Update `.codex/*` evidence documents.

**Interfaces:**
- Consumes: Task 6 PASS.
- Produces: rotated/revoked exposed acceptance credentials and final Phase 0 closure evidence.

- [ ] **Step 1: Gate credential rotation on real E2E PASS**

If Task 6 is `FAIL`, `NOT COMPLETED`, or `NOT EXECUTED`, **do not rotate/revoke the current working acceptance keys**. Record the hygiene task as pending.

- [ ] **Step 2: After real E2E PASS, rotate/revoke exposed acceptance keys**

Operator action:

```text
create replacement key(s)
verify replacement fast smoke
revoke old exposed key(s)
verify old key next protected request -> 401
```

Do not print raw keys in Codex output.

- [ ] **Step 3: Move smoke harness credential loading to environment/ignored local configuration**

Use environment variables such as:

```text
SRA_SMOKE_OPENWEBUI_KEY
SRA_SMOKE_READONLY_KEY
```

Do not add replacement values to Git.

- [ ] **Step 4: Re-run final repository gate after hygiene changes**

Repeat Task 5 targeted/full/static checks and record exact results.

- [ ] **Step 5: Final report**

Report exactly:

```text
Repository
Branch
Baseline commit
Resulting commit (if committed)
Design version: v3
Authoritative Review: v3
Plan version: v6.1
Changed files
Behavior changes
Tests executed
Exact pass/fail/error/warning counts
Fast live security smoke result
Real long Agent E2E: PASS / FAIL / NOT EXECUTED
Evidence of actual Elasticsearch retrieval
Evidence of report/analysis Agent route/execution
Word export/download result
Credential handling: preserved pending E2E / rotated after E2E
Deviations from Plan v6.1
Remaining issues / risks
```

Only if repository gates are freshly green, no Blocking/Major finding remains, and the real ES + long Agent + signed Word chain actually passes may the report state:

```text
Phase 0 v3 repository security gate passed after Plan v6.1 completion.
Phase 0 v3 deployment acceptance passed with real Elasticsearch retrieval, long-running report Agent execution, and signed Word export.
```

If Codex cannot access the operator deployment, use:

```text
Repository implementation verification completed to the extent available, but Phase 0 deployment acceptance remains pending because the real Elasticsearch/long-Agent/Word E2E was NOT EXECUTED. Existing working acceptance credentials were intentionally left unchanged.
```
