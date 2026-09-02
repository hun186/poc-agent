# SRA Unified API Security Boundary Implementation Plan — v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one fail-closed SRA API authentication/authorization boundary that protects existing OpenWebUI Agent APIs and report/job APIs while preserving browser-clickable citation/Word downloads through signed URLs.

**Architecture:** Keep the existing Editor user-token/RBAC implementation intact, add a separate high-entropy service-key credential type, and resolve both credential types into a transport-neutral `AuthPrincipal`. Agent/report/job routes authorize by explicit scopes; job records are principal-owned; OpenWebUI uses one administrator-configured service key; browser resource links use HMAC-signed capability URLs instead of exposing service credentials.

**Tech Stack:** Python, FastAPI, Pydantic, existing JSON auth storage, SQLite job store, HMAC/SHA-256, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v2.md`

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

- **Canonical runtime namespace is `api.*`.** New files physically under `sra_api/security/` are imported as `api.security.*`. Do not introduce `sra_api.security.*` runtime imports.
- Stabilize the existing Editor auth singleton/reload behavior before adding new security state.
- Service-key file mutations require both in-process and cross-process locking across the entire read-modify-write transaction.
- Job DB owner migration is a mandatory transactional table rebuild; it is not an optional ALTER-only path.
- Signed browser capabilities use exact canonical resource/representation binding and the single query parameter `sig`.
- Browser-facing legacy Word links MUST resolve and sign an exact `turn_id`; "latest turn" is authenticated-direct-client compatibility only.
- Reuse existing `PRODUCTION_ENVS={"prod","production"}` semantics for signing-secret fail-closed policy.
- `/docs` and `/openapi.json` remain public by explicit policy; `/redoc` is disabled unless an existing operational dependency is discovered.

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
- Create: `sra_api/security/file_lock.py`
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
- Create: `tests/test_runtime_import_namespace.py`
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


## Task 0: Stabilize Editor auth module identity and baseline

**Files:**
- Modify: `sra_api/routers/editor_dependencies.py`
- Modify: affected tests currently importing stateful runtime routers through `sra_api.*`
- Create: `tests/test_runtime_import_namespace.py`
- Modify: `tests/test_auth_store_security.py`

**Interfaces:**
- Canonical runtime import namespace: `api.*`
- Existing `current_user()` / `require_role()` external behavior remains unchanged
- `editor_dependencies` resolves `api.services.auth_store.AUTH_STORE` through the module object rather than capturing the singleton by value

- [ ] **Step 1: Reproduce the Editor baseline both standalone and combined**

Run the exact auth role test alone and then with `tests/test_api_security_boundaries.py`.

Record results before modification.

- [ ] **Step 2: Add a failing stale-singleton regression**

Reload `api.services.auth_store`, then verify `editor_dependencies.current_user()` observes the reloaded module's current `AUTH_STORE` rather than an object captured before reload.

- [ ] **Step 3: Add canonical namespace regression**

The test must fail if stateful application/auth/security modules are imported simultaneously under both `api.*` and `sra_api.*`.

At minimum guard:

```text
services.auth_store
routers.editor_dependencies
security.*
```

Migrate tests that currently import stateful routers/auth code using `sra_api.*` to `api.*`.

Do NOT attempt to make two separately imported Python module names magically share a singleton; prevent the dual import instead.

- [ ] **Step 4: Change `editor_dependencies.py` to reference the auth-store module**

Use the equivalent of:

```python
import api.services.auth_store as auth_store_module
```

and resolve:

```python
auth_store_module.AUTH_STORE
```

inside dependency execution.

Constants/types may remain imported directly if immutable, but no mutable singleton is captured by value.

- [ ] **Step 5: Run standalone and combined Editor auth suites**

Required outcome: the pre-existing superuser `/v1/auth/users` role-options test returns `200` and the combined suite no longer changes that result.

- [ ] **Step 6: Commit this stabilization separately**

This commit must contain no service-key/signed-URL feature work.

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

The known Editor auth role-options failure from the pre-review baseline MUST already be resolved by Task 0. If it still fails, stop Phase 0 implementation.

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
- Create: `sra_api/security/file_lock.py`
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

Also verify:
- raw key never appears in HTTP list output, audit, logs, exceptions or `repr`;
- stored digest never appears in user-facing/admin list output, audit, logs, exceptions or `repr`;
- the protected service-key persistence file (and any filesystem recovery copy) may contain the digest by design and must remain owner-only.

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=. pytest -q tests/test_service_key_store.py
```

- [ ] **Step 3: Implement using existing atomic JSON-store conventions**

Use:

- cryptographically secure randomness (`secrets`);
- SHA-256 digest of complete high-entropy raw key;
- `hmac.compare_digest` for verification;
- in-process `RLock`;
- OS-level inter-process lock file across complete read-normalize-mutate-write;
- stdlib POSIX `fcntl.flock` / Windows `msvcrt.locking` abstraction or equivalent;
- owner-only permissions for store/lock/temp/recovery files where supported;
- no plaintext persistence.

Add a multiprocessing regression where concurrent CLI/store writers cannot lose one another's updates.

Malformed/corrupt JSON must raise a safe operational error and preserve the original bytes; it must never be silently replaced by an empty store.

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
  - `optional_principal(...) -> AuthPrincipal | None`
  - `require_scopes(*required_scopes)`
  - `require_principal_or_capability(...)` for signed-resource routes
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

`optional_principal()` contract:
- absent Authorization → `None`;
- malformed/invalid/revoked/expired Authorization → `401`.

`require_principal_or_capability(...)` contract:
- valid Authorization path is authoritative;
- valid-but-insufficient principal → `403`;
- absent Authorization may fall back to signed capability;
- invalid Authorization MUST NOT fall back to a valid capability.

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
python -m api.security.cli create-service-key \
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

- [ ] **Step 2: Implement a mandatory transactional table rebuild**

Use `BEGIN IMMEDIATE`.

Create a new versioned table with nullable legacy owner fields, copy all rows, validate row count, then replace the old table.

Create a partial unique index equivalent to:

```sql
CREATE UNIQUE INDEX uq_report_jobs_owner_idempotency
ON report_jobs(owner_kind, owner_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;
```

No request values may be used as SQL identifiers.

- [ ] **Step 3: Add migration rollback tests**

Inject a failure during copy/index/rename and prove the original database remains usable and row count is unchanged.

Verify migrated historical rows have:

```text
owner_kind = NULL
owner_id   = NULL
```

and are admin-only.

- [ ] **Step 4: Protect Job routes with scopes and owner checks**

```text
POST → report:job:create
GET status → report:job:read + owner
GET word → report:job:download + owner
```

Unauthorized cross-owner access returns `404`.

Perform authorization before `_view()`, artifact metadata, status details, error text or any other representation can reveal that the job exists.

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

Canonical signed variants:

```text
doc_detail:
  doc_id + GET

doc_fulltext:
  doc_id + GET + format + download(0|1) + text_layer

legacy_word:
  session_id + exact turn_id + GET
```

Reject duplicate `sig`, duplicate protected parameters, non-canonical boolean aliases, unsupported representation values and representation-changing values that do not match the signed payload.

Use `request.query_params.getlist(...)` or equivalent so duplicate parameters are detectable before normalization.

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

signed doc-detail URL → 200 without Authorization header
signed each fulltext representation URL → 200 without Authorization header
signed Word URL with exact turn_id → 200 without Authorization header

tampered signed doc/Word URL → rejected
expired signed URL → rejected
fulltext capability cannot authorize detail
detail capability cannot authorize fulltext
fulltext format/download/text_layer substitution → rejected
signed Word URL never uses implicit "latest turn"
invalid Authorization + valid sig → rejected
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

Authenticated direct legacy Word access may retain the historical missing-`turn_id` "latest turn" behavior. Browser-facing signed Word links must always resolve and carry a precise turn before signing.

Add `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Content-Type-Options: nosniff` to signed-resource responses where applicable.

- [ ] **Step 5: Regression-test rendered Markdown and OpenAI response shape**

- [ ] **Step 6: Commit**

---

## Task 10: Harden CORS, production-secret policy, and public-route matrix

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

- [ ] **Step 3: Reuse existing production environment semantics**

Import/reuse the existing `PRODUCTION_ENVS={"prod","production"}` policy from auth support.

Production:
- missing/weak `SRA_SIGNED_URL_SECRET` → startup failure;
- no ephemeral fallback.

Development/test:
- deterministic fixture secret;
- optional ephemeral fallback only with a warning;
- never log the generated secret.

- [ ] **Step 4: Add explicit public-route regression matrix**

Assert required public routes stay public and protected routes have dependencies.

Explicit documentation-surface policy:

```text
/openapi.json → public
/docs         → public
/redoc        → disabled unless an existing dependency is proven
/v1/docs/*    → protected-or-signed resource routes
```

Do not confuse Swagger `/docs` with `/v1/docs/{doc_id}`.

- [ ] **Step 5: Run tests and commit**

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
signed fulltext capability does not authorize full `_source` detail
signed detail capability does not authorize fulltext
duplicate/tampered `sig` or protected query keys fail closed
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
signed fulltext query values (`format`, `download`, `text_layer`)
```

Expected: values are treated as data or rejected by validation; never alter query structure/path resolution.

- [ ] **Step 4: Review query-string logging exposure**

Document that signed capability query strings can appear in reverse-proxy/access logs. Do not add application debug logging of `sig` or Authorization values. Where the repository contains proxy examples, document a redacted/no-query logging pattern.

- [ ] **Step 5: Run targeted security suite**

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

# canonical stateful import guard
grep -R "from sra_api.security\|import sra_api.security\|sra_api.services.auth_store" -n sra_api tests api

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

# Codex Prompt — v2 Re-Review Before Implementation

```text
請先不要修改程式碼。

前一次 review 已指出 Phase 0 計劃的阻斷問題。現在請重新審查 v2：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v2.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v2.md

請確認 v2 已完整解決：

1. canonical runtime namespace 固定為 api.*；不得再讓同一個 stateful module 以 api.* 與 sra_api.* 形成雙 singleton。
2. editor_dependencies 不再 capture AUTH_STORE by value，並修復 standalone/combined auth baseline。
3. Job owner/idempotency migration 明確採 BEGIN IMMEDIATE + transactional table rebuild + partial owner-scoped unique index + rollback test。
4. service-key JSON store 具 process RLock + OS-level cross-process lock，鎖住完整 read-modify-write；corrupt store fail closed。
5. service-key raw key 不落盤；digest只存在受保護 persistence/recovery file，不得出現在 API list/log/audit/exception/repr。
6. optional_principal + require_principal_or_capability 的 fail-closed contract完整：
   - 無 Authorization 才可 fallback signed capability
   - invalid Authorization + valid sig 仍拒絕
7. signed URL 使用單一 sig，並精確 bind：
   - doc_detail
   - doc_fulltext + format/download/text_layer
   - legacy_word + session_id + exact turn_id
   並拒絕 duplicate/tampered protected query。
8. browser-facing Word signed URL 不允許 implicit latest turn。
9. production 判定重用既有 PRODUCTION_ENVS={"prod","production"}，production signing secret 缺失/過短 fail startup。
10. /docs、/openapi.json、/redoc 與 /v1/docs/* 已有不混淆的明確政策。
11. signed fulltext capability 無法取得完整 ES _source detail；doc detail 完整 _source 是 Phase 0 明確保留的既有 contract。
12. reverse proxy/access log 對 sig query leakage 已被納入 operations/security docs。
13. SQL injection、IDOR、path traversal、scope escalation、secret leak negative tests足夠。

另外請重新跑：
- auth role-options test standalone
- auth + security-boundary combined baseline

若目前 baseline failure 的根因與 v2 Task 0 假設不同，請指出實際 root cause，不要為了讓 test pass 去降低 RBAC assertion。

只回覆：
- v2 是否仍有 blocking issue
- Task 0 root-cause 判斷
- 需要再調整的檔案/contract
- exact baseline test結果

若無阻斷，最後明確寫：
「可依 Phase 0 v2 計劃實作」

此階段不要修改 code。
```

# Codex Prompt — v2 Implementation

```text
請依 approved v2 文件實作 Phase 0：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v2.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v2.md

先依 AGENTS.md 載入 .codex 專案記憶。

重要：Task 0 是 blocking prerequisite。
在新增 service key / signed URL 之前，先修復並驗證現有 Editor auth module/singleton baseline。

不可跳過的 contract：

A. Import / Editor auth
- canonical stateful runtime namespace = api.*
- 新 security files實體放 sra_api/security，但 runtime import = api.security.*
- 禁止 api.services.auth_store 與 sra_api.services.auth_store 雙載入形成兩個 AUTH_STORE
- editor_dependencies 不得 capture AUTH_STORE by value
- standalone + combined Editor auth baseline 必須全綠

B. Service key
- >=256-bit random
- sra_sk_* format
- raw secret只在 create時顯示一次
- SHA-256 digest可存在 owner-only persistence/recovery file
- raw/digest不得出現在 list/log/audit/exception/repr
- RLock + OS-level cross-process lock鎖住完整 read-modify-write
- corrupt store fail closed且不得覆蓋原檔
- service key不可進 Editor user-only API

C. Unified principal
- current_principal
- optional_principal
- require_scopes
- require_principal_or_capability
- invalid Authorization + valid sig 不可 fallback

D. Protected routes
- GET /v1/models → model:read
- POST /v1/chat/completions → model:invoke
- POST /v1/report/word → report:sync
- Job create/read/download → scopes + owner
- docs/export → authenticated direct scope OR exact signed capability

E. Job migration
- mandatory BEGIN IMMEDIATE table rebuild
- owner_kind/owner_id
- legacy owner NULL, admin-only
- partial UNIQUE(owner_kind, owner_id, idempotency_key) WHERE key IS NOT NULL
- rollback test
- authorization在任何 _view/metadata/artifact detail前完成
- cross-owner → 404
- SQL全面 parameterized

F. Signed capability
- one query parameter: sig
- doc_detail binds exact doc_id
- doc_fulltext binds doc_id + format + canonical download 0|1 + text_layer
- legacy_word binds session_id + exact turn_id
- browser signed Word不可使用 latest-turn implicit behavior
- reject duplicate sig/protected params、tampering、representation substitution
- no credentials inside URL
- signed response: Cache-Control no-store + Referrer-Policy no-referrer + nosniff
- query sig 不可寫入 application debug log
- operations docs說明 reverse-proxy query logging leakage

G. Environment / docs
- production semantics重用既有 PRODUCTION_ENVS
- production缺/弱 SRA_SIGNED_URL_SECRET → startup fail
- /openapi.json public
- /docs public
- /redoc disabled unless existing dependency is demonstrated
- /v1/docs/* 是 protected resource，不可與 Swagger /docs 混淆

H. OpenWebUI
- admin只設定一把 OpenWebUI service key
- scopes只有 model:read + model:invoke
- end users不用設定/知道 key
- Batch Scheduler未來使用另一把 key

不要擴充 Batch Scheduler、Windows GUI、Server Dashboard、OAuth/OIDC、Redis/Celery/PostgreSQL。

採 TDD task-by-task。
每個 blocking/security task測試後再進下一個。

完成後執行：
1. plan全部 targeted tests
2. affected API regression tests
3. `PYTHONPATH=. pytest tests -q --tb=short`
4. `python -m compileall sra_api`
5. `git diff --check`
6. canonical namespace guard
7. credential/sig leak review
8. service-key concurrent process mutation test
9. Job migration rollback test
10. manual no-key/OpenWebUI-key/Batch-key/revoked-key/signed-link smoke tests

最後回報 exact pass/fail counts；未執行的測試不得宣稱成功。
```

# Codex Prompt — v2 Post-Implementation Security Review

```text
請不要新增 Batch/GUI 功能。

針對 Phase 0 v2 做 adversarial security review，並實際嘗試下列 bypass：

1. 無 Authorization 直接 models/chat/report/job。
2. spoof X-OpenWebUI-*、X-Session-Id、Origin/CORS。
3. 同一 stateful auth/security module 是否仍可雙 namespace載入造成第二 singleton。
4. service key scope escalation與 Editor admin誤用。
5. revoked/expired key。
6. concurrent CLI/API service-key create/revoke lost update。
7. corrupt service-key store是否會被空 store覆寫。
8. Job cross-owner IDOR、legacy unowned policy、owner-scoped idempotency。
9. Job migration rollback與既有 rows完整性。
10. signed detail/fulltext capability substitution。
11. format/download/text_layer query tampering、duplicate sig、duplicate protected params。
12. signed Word session/turn substitution與 implicit latest-turn bypass。
13. invalid Authorization + valid sig fallback bypass。
14. raw service key / digest / Authorization / sig 是否出現在 response/log/audit/exception/repr。
15. SQL injection、dynamic SQL、path traversal。
16. /docs vs /v1/docs policy是否正確。
17. production signing secret fail-open。
18. access log / reverse proxy是否可能記錄 sig query，文件是否明確警示。

回覆：
- Critical / High / Medium / Low findings
- reproducible steps
- affected endpoints/files
- fixes
- exact tests run/results

若沒有 blocking/high finding，最後明確寫：
「Phase 0 v2 security gate passed」
```
