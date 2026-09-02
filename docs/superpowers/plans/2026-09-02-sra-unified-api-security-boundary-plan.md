# SRA Unified API Security Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one fail-closed SRA API authentication/authorization boundary that protects existing OpenWebUI Agent APIs and report/job APIs while preserving browser-clickable citation/Word downloads through signed URLs.

**Architecture:** Keep the existing Editor user-token/RBAC implementation intact, add a separate high-entropy service-key credential type, and resolve both credential types into a transport-neutral `AuthPrincipal`. Agent/report/job routes authorize by explicit scopes; job records are principal-owned; OpenWebUI uses one administrator-configured service key; browser resource links use HMAC-signed capability URLs instead of exposing service credentials.

**Tech Stack:** Python, FastAPI, Pydantic, existing JSON auth storage, SQLite job store, HMAC/SHA-256, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design.md`

## Global Constraints

- Baseline is current `poc-agent(7)` behavior.
- Do not rewrite Agent routing, retrieval, prompt, session, memory, or Word rendering logic.
- Existing Editor authentication/RBAC remains backward-compatible.
- Service API keys MUST NOT authenticate as Editor users.
- Missing/invalid/revoked/expired credentials fail closed.
- Authorization MUST be enforced at API dependencies/service boundaries, not only in UI code.
- Do not use source IP, CORS, custom OpenWebUI headers, session IDs, filenames, or job IDs as authentication.
- Service-key plaintext is shown once and never persisted/logged.
- SQL operations added/modified by this work must use parameters; no request data may be interpolated into SQL.
- OpenWebUI service key and Batch Scheduler service key are separate credentials.
- Do not add Redis, Celery, PostgreSQL, OAuth/OIDC, Batch GUI, Windows GUI, or Server Dashboard in this phase.
- Preserve `/healthz` and required auth bootstrap/login endpoints as public.
- Replace old tests that intentionally require Agent routes to remain public with tests for the new protected contract; do not merely delete coverage.

---

## File Structure

### New security package

- Create: `sra_api/security/__init__.py`
- Create: `sra_api/security/models.py`
  - `AuthPrincipal`
  - service-key public/admin models
- Create: `sra_api/security/scopes.py`
  - scope constants
  - validation registry
  - user-role → SRA-scope mapping
- Create: `sra_api/security/service_key_store.py`
  - atomic JSON persistence
  - create/list/revoke/resolve
  - plaintext-secret never persisted
- Create: `sra_api/security/principal.py`
  - unified bearer principal resolution
  - `current_principal`
  - `require_scopes`
- Create: `sra_api/security/signed_urls.py`
  - sign/verify resource capability tokens
  - exact resource binding
- Create: `sra_api/security/cli.py`
  - local service-key creation/list/revoke tooling

### New/modified routes

- Create: `sra_api/routers/service_keys.py`
  - superuser-only key administration API
- Modify: `sra_api/main.py`
  - include router
  - hardened CORS
  - initialize security stores/config
- Modify: `sra_api/routers/chat.py`
  - `model:read` / `model:invoke`
  - signed Word export metadata
- Modify: `sra_api/routers/chat_support.py`
  - signed citation hrefs
- Modify: `sra_api/routers/export.py`
  - protect sync report
  - authenticated-or-signed legacy Word export
- Modify: `sra_api/routers/docs.py`
  - authenticated-or-signed document access
- Modify: `sra_api/routers/report_jobs.py`
  - scope authorization
  - owner isolation
- Modify: `sra_api/services/report_job_service.py`
  - principal owner passed at creation
- Modify: `sra_api/services/report_job_store.py`
  - owner columns/migration
  - owner-scoped idempotency
- Modify: `sra_api/core/presenters/citation_views.py`
  - signed document/fulltext URLs
- Modify: `sra_api/core/presenters/markdown_presenter.py`
  - signed legacy Word URL
- Modify: `.gitignore`
  - service-key runtime store

### Tests

- Create: `tests/test_service_key_store.py`
- Create: `tests/test_service_key_api.py`
- Create: `tests/test_unified_principal.py`
- Create: `tests/test_agent_api_auth.py`
- Create: `tests/test_signed_resource_urls.py`
- Create: `tests/test_job_authorization.py`
- Create: `tests/test_security_cors.py`
- Modify: `tests/test_api_security_boundaries.py`
- Modify: existing report/job/chat/docs/export regression tests as necessary

### Documentation

- Create: `docs/security/sra-api-security-boundary.md`
- Create: `docs/security/openwebui-service-key-setup.md`
- Create: `docs/security/service-key-operations.md`
- Create/update: `docs/architecture/sra-api-security-boundary.svg`
- Modify: `README.md`
- Modify: `SRA_Word_Report_Dual_Mode_Test_Guide.md` if tracked in repo
- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/memory.md`
- Modify: `.codex/backlog.md`
- Modify: `.codex/known_issues.md`

---

## Task 1: Establish and verify the pre-change security baseline

**Files:**
- Test: `tests/test_api_security_boundaries.py`
- Read: `sra_api/routers/editor_dependencies.py`
- Read: `sra_api/services/auth_tokens.py`
- Read: `sra_api/services/auth_store.py`
- Read: `sra_api/routers/chat.py`
- Read: `sra_api/routers/export.py`
- Read: `sra_api/routers/docs.py`
- Read: `sra_api/routers/report_jobs.py`

**Interfaces:**
- Consumes: current Editor `current_user()` and `require_role()`
- Produces: verified baseline report before modifying auth

- [ ] **Step 1: Run current targeted security/auth regression tests**

Run:

```bash
PYTHONPATH=. pytest -q \
  tests/test_api_security_boundaries.py \
  tests/test_auth_store_security.py \
  tests/test_report_jobs_api.py \
  tests/test_report_job_store.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py
```

Expected: record exact pass/fail counts. Do not proceed on unexplained baseline failures.

- [ ] **Step 2: Inventory route dependencies**

Generate a route matrix covering at least:

```text
/v1/models
/v1/chat/completions
/v1/report/word
/v1/report/jobs
/v1/report/jobs/{job_id}
/v1/report/jobs/{job_id}/word
/v1/docs/{doc_id}
/v1/docs/{doc_id}/fulltext
/v1/export/word
/v1/auth/*
/healthz
```

Record which routes are currently public vs. protected.

- [ ] **Step 3: Commit only if baseline documentation/test adjustments are needed**

Do not alter runtime behavior in this task.

---

## Task 2: Add scope registry and unified principal model

**Files:**
- Create: `sra_api/security/__init__.py`
- Create: `sra_api/security/models.py`
- Create: `sra_api/security/scopes.py`
- Test: `tests/test_unified_principal.py`

**Interfaces:**
- Produces:
  - `AuthPrincipal`
  - registered scope constants
  - `scopes_for_user_role(role: str) -> frozenset[str]`

- [ ] **Step 1: Write failing tests for principal and scope registry**

Cover:

```python
def test_unknown_scope_is_rejected(): ...
def test_data_reader_receives_normal_self_service_agent_scopes(): ...
def test_superuser_receives_job_admin_scope(): ...
def test_principal_id_is_kind_and_subject(): ...
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=. pytest -q tests/test_unified_principal.py
```

- [ ] **Step 3: Implement minimum models/scopes**

Initial registry:

```text
model:read
model:invoke
report:sync
report:job:create
report:job:read
report:job:download
report:job:admin
document:read
report:legacy-download
```

Keep future Batch-management scopes out of this phase.

- [ ] **Step 4: Run tests**

Expected: pass.

- [ ] **Step 5: Commit**

Suggested:

```bash
git add sra_api/security tests/test_unified_principal.py
git commit -m "feat(security): add SRA principal and scope model"
```

---

## Task 3: Implement secure service-key persistence

**Files:**
- Create: `sra_api/security/service_key_store.py`
- Test: `tests/test_service_key_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - `ServiceKeyStore.create(name, scopes, created_by, expires_at=None)`
  - `ServiceKeyStore.resolve(raw_key)`
  - `ServiceKeyStore.list_keys()`
  - `ServiceKeyStore.revoke(key_id, revoked_by)`
  - default file from `SRA_SERVICE_KEYS_FILE`

- [ ] **Step 1: Write failing security tests**

Must cover:

```text
generated key starts with sra_sk_
secret has high entropy
store never contains plaintext key
list API model never contains plaintext key
invalid key does not resolve
revoked key does not resolve
expired key does not resolve
unknown scope cannot be stored
atomic store survives reload
malformed store fails safely
```

Also search persisted file and audit-like serialized output for the raw key.

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=. pytest -q tests/test_service_key_store.py
```

- [ ] **Step 3: Implement using existing atomic JSON-store conventions**

Use:

- cryptographically secure randomness (`secrets`);
- SHA-256 digest of complete high-entropy raw key;
- `hmac.compare_digest` for verification;
- lock around read/write mutation;
- no plaintext persistence.

- [ ] **Step 4: Add `.sra_service_keys.json` and temp patterns to `.gitignore`**

- [ ] **Step 5: Run tests**

- [ ] **Step 6: Commit**

---

## Task 4: Add unified Bearer principal dependency

**Files:**
- Create: `sra_api/security/principal.py`
- Test: `tests/test_unified_principal.py`
- Modify only if required: `sra_api/routers/editor_dependencies.py`

**Interfaces:**
- Produces:
  - `current_principal(...) -> AuthPrincipal`
  - `require_scopes(*required_scopes)`
- Preserves:
  - existing `current_user() -> AuthUser`
  - existing `require_role()`

- [ ] **Step 1: Write failing tests**

Cover:

```text
missing bearer → 401
malformed bearer → 401
valid user token → user principal
valid service key → service principal
invalid service key → 401
revoked service key → 401
valid principal missing scope → 403
service key passed to Editor current_user → 401
```

- [ ] **Step 2: Run and confirm failure**

- [ ] **Step 3: Implement resolver**

Resolution order:

```text
Bearer sra_sk_* → ServiceKeyStore
other Bearer    → existing parse_token/current-user validation logic
```

Avoid duplicating user validation logic: extract/reuse a helper if needed while preserving current Editor behavior.

- [ ] **Step 4: Add denied-auth/authz audit events without credential values**

- [ ] **Step 5: Run tests**

- [ ] **Step 6: Commit**

---

## Task 5: Add superuser service-key administration API and local CLI

**Files:**
- Create: `sra_api/routers/service_keys.py`
- Create: `sra_api/security/cli.py`
- Modify: `sra_api/main.py`
- Test: `tests/test_service_key_api.py`

**Interfaces:**
- HTTP:
  - `POST /v1/auth/service-keys`
  - `GET /v1/auth/service-keys`
  - `POST /v1/auth/service-keys/{key_id}/revoke`
- CLI:
  - create
  - list
  - revoke

- [ ] **Step 1: Write failing API tests**

Must verify:

```text
anonymous → 401
non-superuser → 403
superuser can create
create response returns plaintext key once
GET list never returns plaintext key or digest
revoke works
revoked key immediately fails authentication
audit event excludes secret
invalid scope → 422/400
```

- [ ] **Step 2: Write failing CLI tests**

CLI-generated raw secret appears on stdout only for create and is persisted only as digest.

- [ ] **Step 3: Implement HTTP routes using existing `require_superuser`**

Do not authorize service principals to these routes.

- [ ] **Step 4: Implement local CLI**

Example:

```bash
python -m sra_api.security.cli create-service-key \
  --name openwebui-production \
  --scope model:read \
  --scope model:invoke
```

Do not accept a caller-supplied raw secret as a CLI argument.

- [ ] **Step 5: Run tests and commit**

---

## Task 6: Protect `/v1/models`, `/v1/chat/completions`, and sync Word

**Files:**
- Modify: `sra_api/routers/chat.py`
- Modify: `sra_api/routers/export.py`
- Test: `tests/test_agent_api_auth.py`
- Modify: `tests/test_api_security_boundaries.py`
- Modify: `tests/test_report_word_api.py`
- Modify: `tests/test_chat_word_export_metadata.py`

**Interfaces:**
- `GET /v1/models` requires `model:read`
- `POST /v1/chat/completions` requires `model:invoke`
- `POST /v1/report/word` requires `report:sync`

- [ ] **Step 1: Replace the old "agent routes remain public" test with fail-closed tests**

Do not delete security-boundary coverage.

New assertions:

```text
no credential → 401
wrong scope → 403
correct service scope → existing success behavior
valid user principal → existing success behavior
```

- [ ] **Step 2: Run tests and observe failures**

- [ ] **Step 3: Add `Depends(require_scopes(...))` without changing Agent logic**

Do not pass principal into the Agent pipeline unless needed for audit metadata.

- [ ] **Step 4: Verify OpenAI-compatible response shape unchanged**

- [ ] **Step 5: Run targeted regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/test_agent_api_auth.py \
  tests/test_api_security_boundaries.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_turn_execution_service.py
```

- [ ] **Step 6: Commit**

---

## Task 7: Add owner isolation to Report Jobs

**Files:**
- Modify: `sra_api/services/report_job_store.py`
- Modify: `sra_api/services/report_job_service.py`
- Modify: `sra_api/routers/report_jobs.py`
- Test: `tests/test_job_authorization.py`
- Modify: `tests/test_report_job_store.py`
- Modify: `tests/test_report_jobs_api.py`
- Modify: `tests/test_report_job_worker.py`
- Modify: `tests/test_report_jobs_lifecycle.py`

**Interfaces:**
- New persistent fields:
  - `owner_kind`
  - `owner_id`
- `create_job(..., owner_kind, owner_id, ...)`
- idempotency uniqueness includes owner

- [ ] **Step 1: Write migration and authorization tests before schema changes**

Cover:

```text
new job stores owner
owner can read
owner can download
different user/service receives 404
superuser/job-admin can read cross-owner
legacy unowned row accessible only by admin
same idempotency key for different owners creates independent jobs
same owner + same key + same hash reuses job
same owner + same key + different hash → 409
```

- [ ] **Step 2: Add SQLite migration**

Use hardcoded migration SQL only. Never interpolate request fields into schema/table/column names.

- [ ] **Step 3: Change idempotency unique boundary to owner-scoped semantics**

If SQLite cannot directly alter the existing unique constraint safely, perform an explicit table migration with tests and backup-safe transaction semantics.

- [ ] **Step 4: Protect Job routes with scopes and owner checks**

```text
POST → report:job:create
GET status → report:job:read + owner
GET word → report:job:download + owner
```

Unauthorized cross-owner access returns `404`.

- [ ] **Step 5: Preserve existing 404/409/500 artifact contract**

- [ ] **Step 6: Run all Job tests**

- [ ] **Step 7: Commit**

---

## Task 8: Implement HMAC-signed resource URLs

**Files:**
- Create: `sra_api/security/signed_urls.py`
- Test: `tests/test_signed_resource_urls.py`

**Interfaces:**
- `sign_resource(...) -> str`
- `verify_resource_token(...)`
- Config:
  - `SRA_SIGNED_URL_SECRET`
  - `SRA_SIGNED_URL_TTL_SECONDS`

- [ ] **Step 1: Write failing cryptographic contract tests**

Cover:

```text
valid token verifies
expired token fails
modified resource id fails
modified method fails
modified representation/options fail
token for doc A cannot open doc B
token for session/turn A cannot export session/turn B
malformed token fails without stack trace
production missing/short signing secret fails startup/config validation
```

- [ ] **Step 2: Implement HMAC-SHA256 token**

Use:

- canonical JSON payload;
- URL-safe base64;
- constant-time signature comparison;
- explicit version;
- exact resource binding;
- bounded TTL.

Do not put service/user credentials in signed payload.

- [ ] **Step 3: Run tests and commit**

---

## Task 9: Protect docs/legacy export and generate signed OpenWebUI links

**Files:**
- Modify: `sra_api/routers/docs.py`
- Modify: `sra_api/routers/export.py`
- Modify: `sra_api/routers/chat.py`
- Modify: `sra_api/routers/chat_support.py`
- Modify: `sra_api/core/presenters/citation_views.py`
- Modify: `sra_api/core/presenters/markdown_presenter.py`
- Test: `tests/test_signed_resource_urls.py`
- Modify: `tests/test_api_security_boundaries.py`
- Modify: citation/export tests

**Interfaces:**
- Resource endpoint may authorize through:
  1. valid principal + proper direct-read scope; OR
  2. valid signed capability token bound to that resource.
- Chat responses produce signed links.

- [ ] **Step 1: Write failing route tests**

Required:

```text
unsigned anonymous doc detail → 401
unsigned anonymous fulltext → 401
unsigned anonymous legacy Word export → 401

document:read principal → 200
report:legacy-download principal → 200

signed doc URL → 200 without Authorization header
signed Word URL → 200 without Authorization header

tampered signed doc/Word URL → rejected
expired signed URL → rejected
```

- [ ] **Step 2: Update citation builders**

Every browser-facing citation href generated for OpenWebUI must be signed.

Check both:

```text
chat_support.build_citations()
citation_views.py
```

- [ ] **Step 3: Update Word links**

Check both:

```text
chat response context.word_export.url
markdown_presenter.py
```

Do not leave an unsigned alternate Word URL in the same response.

- [ ] **Step 4: Protect docs/export routes**

Support authenticated direct clients as well as signed browser links.

- [ ] **Step 5: Regression-test rendered Markdown and OpenAI response shape**

- [ ] **Step 6: Commit**

---

## Task 10: Harden CORS and public-route policy

**Files:**
- Modify: `sra_api/main.py`
- Create: `tests/test_security_cors.py`
- Modify: `tests/test_api_security_boundaries.py`

**Interfaces:**
- production with no configured cross-origin list → same-origin only
- wildcard mode, if retained for development, must not be credentialed

- [ ] **Step 1: Write failing CORS tests**

Cover:

```text
Authorization allowed for configured browser origin
Idempotency-Key allowed
unconfigured origin not granted in production
wildcard + credentials combination is not emitted
server-to-server behavior unaffected
```

- [ ] **Step 2: Implement hardened CORS configuration**

Do not treat CORS as authentication.

- [ ] **Step 3: Add explicit public-route regression matrix**

Assert required public routes stay public and protected routes have dependencies.

- [ ] **Step 4: Run tests and commit**

---

## Task 11: Security negative testing

**Files:**
- Create/modify: `tests/test_agent_api_auth.py`
- Create/modify: `tests/test_job_authorization.py`
- Create/modify: `tests/test_signed_resource_urls.py`
- Modify: `tests/test_api_security_boundaries.py`

- [ ] **Step 1: Add authorization-bypass attempts**

Test:

```text
X-Session-Id without Authorization does not authenticate
X-OpenWebUI-Chat-Id does not authenticate
spoofed OpenWebUI headers do not authenticate
CORS origin does not authenticate
job_id knowledge does not authorize
session_id/turn_id knowledge does not authorize legacy export
service key with model:read cannot invoke model
OpenWebUI key cannot create batch job
Batch key cannot invoke chat unless explicitly granted
service key cannot list users or manage service keys
```

- [ ] **Step 2: Add secret-leak tests**

Ensure:

```text
401/403 response does not echo raw credential
audit event does not contain raw credential
service-key JSON does not contain raw credential
service-key listing does not expose digest
```

- [ ] **Step 3: Add SQL/path-injection regressions around changed Job storage**

Examples should include quote characters, SQL metacharacters, Unicode, and traversal strings in:

```text
idempotency key
service-key name
metadata
filename
job id URL
```

Expected: values are treated as data or rejected by validation; never alter query structure/path resolution.

- [ ] **Step 4: Run targeted security suite**

---

## Task 12: OpenWebUI integration test

**Files:**
- Test: `tests/test_agent_api_auth.py`
- Documentation: `docs/security/openwebui-service-key-setup.md`

- [ ] **Step 1: Create a test service key with only**

```text
model:read
model:invoke
```

- [ ] **Step 2: Verify**

```text
GET /v1/models → 200
POST /v1/chat/completions → 200
POST /v1/report/jobs → 403
```

- [ ] **Step 3: Verify chat output contains working signed citation/Word links**

Browser-style GET uses no Authorization header.

- [ ] **Step 4: Revoke key and verify subsequent model call → 401**

- [ ] **Step 5: Document OpenWebUI admin configuration**

Document that the API key is configured once by an OpenWebUI administrator and is not configured by each end user.

---

## Task 13: Operational documentation and architecture diagram

**Files:**
- Create: `docs/security/sra-api-security-boundary.md`
- Create: `docs/security/openwebui-service-key-setup.md`
- Create: `docs/security/service-key-operations.md`
- Create/update: `docs/architecture/sra-api-security-boundary.svg`
- Modify: `README.md`
- Modify: `SRA_Word_Report_Dual_Mode_Test_Guide.md` if present

- [ ] **Step 1: Document endpoint security matrix**

- [ ] **Step 2: Document service-key lifecycle**

Create/list/revoke, secret shown once, backup implications.

- [ ] **Step 3: Document OpenWebUI setup**

Example:

```text
Base URL: http://192.168.0.133:9002/v1
API Key:  sra_sk_...
```

- [ ] **Step 4: Update JavaScript/Python testing examples**

They must include Authorization after security enforcement.

- [ ] **Step 5: Add SVG**

Show:

```text
OpenWebUI --service key--> SRA principal resolver --> scoped Agent APIs
Batch Scheduler --different service key--> Job APIs
Editor/GUI --user bearer--> user principal/RBAC
SRA chat --> signed citation/Word URL --> browser
```

Maintain only one canonical SVG under `docs/architecture/`.

- [ ] **Step 6: Commit docs**

---

## Task 14: `.codex` project memory and contract update

**Files:**
- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/memory.md`
- Modify: `.codex/backlog.md`
- Modify: `.codex/known_issues.md`

- [ ] **Step 1: Record new authentication contract**

Explicitly remove statements saying OpenWebUI agent routes remain public.

- [ ] **Step 2: Record credential types/scopes**

- [ ] **Step 3: Record signed URL behavior/expiry**

- [ ] **Step 4: Record known limitations**

At minimum:

```text
OpenWebUI service principal does not identify individual OpenWebUI end user
service-key store is single-machine file persistence
signed URLs are bearer capabilities until expiry
historical OpenWebUI messages may contain expired signed links
```

- [ ] **Step 5: Add future backlog**

```text
per-end-user OpenWebUI identity propagation
service-key rotation workflow
rate limits/quotas by principal
Batch Scheduler / Server Dashboard / Windows GUI
```

---

## Task 15: Final verification and security gate

- [ ] **Step 1: Run all security/auth targeted tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_unified_principal.py \
  tests/test_agent_api_auth.py \
  tests/test_signed_resource_urls.py \
  tests/test_job_authorization.py \
  tests/test_security_cors.py \
  tests/test_api_security_boundaries.py \
  tests/test_auth_store_security.py
```

- [ ] **Step 2: Run affected API regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/test_turn_execution_service.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_export_word_service.py \
  tests/test_report_jobs_api.py \
  tests/test_report_job_store.py \
  tests/test_report_job_worker.py \
  tests/test_report_jobs_lifecycle.py
```

- [ ] **Step 3: Run full suite**

```bash
PYTHONPATH=. pytest tests -q --tb=short
```

- [ ] **Step 4: Static/syntax verification**

```bash
python -m compileall sra_api
git diff --check
```

- [ ] **Step 5: Search for accidental plaintext credential handling**

Review changes for:

```text
Authorization logging
service-key raw values in JSON/audit
debug print of headers
signed/user token logging
```

- [ ] **Step 6: Manual smoke test**

Without key:

```text
GET /v1/models → 401
POST /v1/chat/completions → 401
```

OpenWebUI service key:

```text
GET /v1/models → 200
POST /v1/chat/completions → success
POST /v1/report/jobs → 403
```

Batch key:

```text
POST /v1/report/jobs → 202
GET own job → 200
GET other principal's job → 404
```

Signed browser URL:

```text
citation → works
Word → works
modified token → fails
```

Revoked key:

```text
next request → 401
```

- [ ] **Step 7: Report exact test results**

Never claim unexecuted tests passed.

---

# Rollout Checklist

Before enforcement reaches the live OpenWebUI environment:

- [ ] Back up auth and job state.
- [ ] Set a stable production `SRA_SIGNED_URL_SECRET` (>=32 bytes).
- [ ] Create `openwebui-production` key locally.
- [ ] Grant only `model:read` and `model:invoke`.
- [ ] Configure that key once in OpenWebUI Admin provider settings.
- [ ] Restart SRA API.
- [ ] Confirm OpenWebUI model list and chat.
- [ ] Confirm browser citation and Word links.
- [ ] Confirm unauthenticated direct API calls return 401.
- [ ] Create a separate batch key only when Batch Scheduler development starts.
- [ ] Revoke temporary/test keys.

---

# Codex Prompt — Review First

```text
請先不要修改程式碼。

請依 AGENTS.md 順序讀取 .codex 專案記憶，然後審查：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan.md

本階段目標只有 Phase 0 Security Foundation：
建立 SRA 統一 API Security Boundary，並收斂目前公開的 OpenWebUI Agent / Report / Job API。

請與目前 branch 實際程式比對，特別確認：

1. 現有 Editor user token、token version、denylist、role hierarchy、require_role() 的實際 contract。
2. /v1/models、/v1/chat/completions、/v1/report/word、Job APIs、/v1/docs、/v1/export/word 現有 dependency 狀況。
3. 是否能在不破壞 Editor auth 的前提下增加 AuthPrincipal + service API key。
4. service key 是否可用獨立 atomic JSON store，且 raw key 僅建立時顯示一次。
5. OpenWebUI 是否只需管理員設定一把 service key，使用者不需自行設定。
6. Job owner isolation 與 owner-scoped idempotency 對現有 SQLite schema 的 migration 方式。
7. OpenWebUI browser citation / Word link 改 signed URL 時，需要修改哪些 presenter / response builder，避免遺漏任何 unsigned alternate URL。
8. 現有 tests 中哪些是刻意要求 agent routes public，必須改成新的 protected regression contract。
9. 是否有任何授權 bypass、IDOR、SQL injection、path traversal、secret logging、CORS 誤用風險未被計劃涵蓋。
10. rollout 是否能先用 local CLI 建 OpenWebUI service key，再啟動 enforce 後的服務，而不需要留下 permanent public compatibility mode。

不要擴充到 Batch Scheduler、Windows GUI、Server Dashboard、Redis/Celery、OAuth/OIDC。

只回覆：
- 開工前必須修正的計劃問題
- 可直接照做的部分
- 實際預計新增/修改檔案
- 現有 targeted test baseline 結果

若沒有阻斷問題，最後明確寫：
「可依此 Phase 0 計劃實作」

此階段不要修改 code。
```

# Codex Prompt — Implementation

```text
請依下列 approved Phase 0 文件完整實作：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan.md

開始前依 AGENTS.md 載入 .codex 專案記憶，並以目前程式碼確認 baseline。

核心要求：

1. 保留現有 Editor user bearer token / RBAC contract。
2. 新增 transport-neutral AuthPrincipal，可解析：
   - existing user bearer token
   - sra_sk_* service API key
3. Service API Key：
   - 至少 256-bit random secret
   - raw key 僅建立時顯示一次
   - 不可 plaintext 落盤或寫 log/audit
   - 可 list / revoke / expiry
   - superuser-only 管理
   - 提供 local CLI，讓正式上線前可先建立 OpenWebUI key
4. OpenWebUI 管理員只需設定一把：
   - model:read
   - model:invoke
   一般 OpenWebUI 使用者不需自行設定或得知 key。
5. Batch Scheduler 未來使用另一把獨立 key，不可和 OpenWebUI 共用。
6. 收斂：
   - GET /v1/models → model:read
   - POST /v1/chat/completions → model:invoke
   - POST /v1/report/word → report:sync
   - Job create/read/download → 對應 job scopes + owner authorization
7. Job SQLite 增加 owner_kind / owner_id。
   - 非 owner 存取回 404，避免 IDOR/resource enumeration。
   - superuser / report:job:admin 可跨 owner。
   - legacy unowned jobs 只允許 admin。
   - Idempotency-Key uniqueness 必須以 owner + key 為邊界。
   - SQL 必須 parameterized，不得將 request input 插入 SQL。
8. /v1/docs/* 與 /v1/export/word 不可繼續永久公開。
   - direct client：authenticated scope
   - OpenWebUI browser click：HMAC signed URL
   - signed URL 必須 bind exact resource + expiry
   - 不得把 service key/user token 放 URL。
9. 必須檢查所有產生 citation / fulltext / Word URL 的地方：
   - chat.py
   - chat_support.py
   - citation_views.py
   - markdown_presenter.py
   - 其他 grep 找到的 URL builder
   不得留下 unsigned alternate browser link。
10. CORS 不是認證。
    - production 不得使用 wildcard origin + credentials。
    - 保留 Authorization / Idempotency-Key 等必要 preflight。
11. Service key 不得通過現有 Editor current_user / require_role。
12. 不要新增永久 public compatibility bypass。
13. 不碰 Agent routing、retrieval、prompt、Word renderer 核心行為。
14. 不引入 Redis、Celery、PostgreSQL、OAuth/OIDC、Batch GUI。

請採 TDD task-by-task 執行。

完成後必須：

- 跑 plan 內全部 security targeted tests
- 跑 affected API regression tests
- 跑 `PYTHONPATH=. pytest tests -q --tb=short`
- 跑 `python -m compileall sra_api`
- 跑 `git diff --check`
- 做 credential leak review
- 更新 security docs / README / SVG
- 更新 `.codex/api_contract.md`、`.codex/architecture.md`、`.codex/decisions.md`、`.codex/memory.md`、`.codex/backlog.md`、`.codex/known_issues.md`

最後回報：
1. 新增/修改檔案
2. AuthPrincipal 與 scope matrix
3. Service key create/list/revoke contract
4. OpenWebUI 管理員設定方式
5. Job owner/idempotency migration
6. signed URL contract 與 TTL
7. public/protected endpoint matrix
8. exact test pass/fail 數
9. 仍存在的限制
10. 下一階段 Batch Scheduler 可以直接重用的 security interface

不得把未執行測試宣稱成功。
```

# Codex Prompt — Post-Implementation Security Review

```text
請先不要新增功能，針對剛完成的 SRA Unified API Security Boundary 做一次 adversarial security review。

重點不是程式風格，而是找出能實際繞過認證/授權的路徑。

請檢查：

- 無 Authorization 是否還能 invoke model/report/job
- spoofed X-OpenWebUI-* / X-Session-Id 是否能繞過
- service key scope escalation
- service key 是否可誤用於 Editor admin API
- revoked/expired key race
- job IDOR / cross-owner read/download
- owner-scoped idempotency isolation
- legacy unowned job policy
- signed URL resource substitution / query tampering / expiry bypass
- 是否還有未簽名 citation/fulltext/Word URL
- plaintext key/token 是否出現在 state/audit/log/exception
- CORS 是否被誤當 security control
- SQL injection / dynamic SQL
- path traversal
- 401 vs 403 vs 404 resource enumeration
- production secret/config fail-open
- test 是否真的覆蓋 protected route matrix

執行必要的 targeted tests，並提供：
1. Critical / High / Medium / Low findings
2. 可重現步驟
3. 受影響檔案/endpoint
4. 建議修正
5. 若無阻斷問題，明確寫「Phase 0 security gate passed」

此 review 階段不要順便實作 Batch Scheduler / GUI。
```
