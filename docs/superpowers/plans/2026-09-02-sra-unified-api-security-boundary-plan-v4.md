# SRA Unified API Security Boundary Completion Implementation Plan — v4

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and harden the already-partially-implemented Phase 0 unified SRA API security boundary so the current source satisfies Design v3 without redesigning completed architecture.

**Architecture:** Preserve the existing `api.*` compatibility namespace, Editor bearer/RBAC system, unified `AuthPrincipal`, service-key store, owner-aware Report Jobs, and HMAC browser capabilities. This plan closes implementation gaps around environment bootstrap, canonical capability validation, audit, service-key correctness, migration validation, CORS/secret policy, and tracked adversarial tests.

**Tech Stack:** Python, FastAPI, Pydantic, SQLite, JSON file persistence, HMAC/SHA-256, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`

**Implementation review:** `docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v1.md`

**Supersedes:** `docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v3.md` **for remaining work from the current baseline only**. Completed v3 architecture is retained and must not be reimplemented unless a task below explicitly hardens it.

## Baseline Metadata

- **Repository:** `poc-agent` source tree; remote URL unavailable in supplied snapshot
- **Branch:** unknown; supplied ZIP contains no `.git` metadata
- **Commit:** unknown; do not invent one
- **Source snapshot:** `poc-agent_20260902-203534.zip`
- **Design:** v3 unchanged
- **Prior plan:** v3
- **Current plan:** v4

When Codex runs in the actual Git repository, it must record the real repository/branch/HEAD commit in its completion report. The current source code is authoritative if any old Plan v3 path/signature has already changed.

## Global Constraints

- Do **not** create Design v4 unless Design v3 proves impossible to implement.
- Do **not** redesign the security architecture, Agent routing/retrieval, Editor RBAC, Report Job execution model, or signed-link model.
- Do **not** reimplement components that already satisfy Design v3 merely because Plan v3 checkboxes are unmarked.
- Canonical runtime namespace remains `api.*`; physical source remains under `sra_api/`.
- Existing Editor user tokens and service keys remain separate credential domains.
- Invalid Authorization is authoritative; never fall back from an invalid header to a valid signed capability.
- Missing/invalid/revoked/expired credentials fail closed.
- Service-key plaintext is returned once and never persisted/logged/audited.
- Stored service-key digest is not returned through HTTP/CLI/listing/logs/audit/exception representations.
- Service-key file mutation retains in-process + cross-process locking over the complete read-modify-write transaction.
- Existing Report Job migration exact order remains unchanged: validate → create staged → copy → validate staged → rename old → rename staged → create partial owner index → validate canonical → drop old → set version 1 → verify → commit.
- SQL values remain parameterized. Do not interpolate request data into SQL.
- Signed capability validation happens before resource lookup/serialization.
- OpenWebUI production key remains only `model:read` + `model:invoke`.
- Batch Scheduler, Windows GUI, Server Dashboard, OIDC/OAuth, Redis/Celery/PostgreSQL, retention/cancel/webhook work remain outside Phase 0.
- Preserve public `/healthz`, `/docs`, `/openapi.json`, auth bootstrap/login routes; `/redoc` remains disabled.
- Use TDD for behavior changes: failing test → implementation → passing targeted test.
- Do not weaken existing tests to make the suite green.

## Current Baseline — Preserve These Implemented Pieces

The following already exist and are not fresh implementation tasks:

```text
AuthPrincipal + scope registry
service-key store + digest + locking + atomic replace
service-key admin route + CLI skeleton
model/chat/sync Word scope enforcement
Report Job owner fields + scope/owner checks
version-0 → version-1 migration skeleton and correct rename/index/drop/version order
signed HMAC token format and link generation
initial docs/export capability checks
initial CORS hardening
security/OpenWebUI documentation
canonical namespace regression
Editor stale AUTH_STORE fix
```

Codex should modify these only where a task below closes a verified gap.

---

## Task 0: Re-baseline the actual repository before continuation

**Files:**
- Read: `AGENTS.md`
- Read: `.codex/memory.md`
- Read: `.codex/backlog.md`
- Read: Design v3, this Plan v4, Implementation Review v1
- Inspect: current Git status and relevant source/tests

**Produces:** a short pre-implementation baseline note in Codex's execution log/report; no architecture changes.

- [ ] **Step 1: Record actual Git identity**

Run in the real repository:

```bash
git remote -v || true
git branch --show-current
git rev-parse HEAD
git status --short
```

Do not invent missing values. If the working tree contains unrelated user changes, preserve them.

- [ ] **Step 2: Confirm current source still matches the review gaps**

Inspect at minimum:

```text
sra_api/main.py
sra_api/security/principal.py
sra_api/security/service_key_store.py
sra_api/security/cli.py
sra_api/security/signed_urls.py
sra_api/routers/docs.py
sra_api/routers/export.py
sra_api/routers/service_keys.py
sra_api/routers/report_jobs.py
sra_api/services/report_job_store.py
config/bootstrap.py
```

If a listed gap is already fixed in the current repository, do not redo it; verify its tests and mark the corresponding step satisfied.

- [ ] **Step 3: Run the current targeted baseline before modifying**

Use the repository's installed dependencies. At minimum:

```bash
PYTHONPATH=. pytest -q \
  tests/test_runtime_import_namespace.py \
  tests/test_auth_store_security.py \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_unified_principal.py \
  tests/test_agent_api_auth.py \
  tests/test_signed_resource_urls.py \
  tests/test_job_authorization.py \
  tests/test_report_job_migration_v1.py \
  tests/test_security_cors.py \
  tests/test_api_security_boundaries.py
```

Record exact pass/fail/error counts. Environment/dependency collection failures must be reported as environment failures, not silently treated as passes.

---

## Task 1: Make security `.env` bootstrap deterministic for API and CLI

**Files:**
- Modify: `sra_api/main.py`
- Modify: `sra_api/security/cli.py`
- Test: create `tests/test_security_env_bootstrap.py`
- Test: create/extend `tests/test_service_key_cli.py`
- Possibly modify: `.gitignore` only for narrow runtime-secret patterns verified in the real repo

**Interfaces:**
- `config.bootstrap.bootstrap_env()` remains the only environment-file loader.
- `SRA_SERVICE_KEYS_FILE` must be resolved after bootstrap and before the process-global API store is instantiated.
- OS environment keeps precedence over `.env.local` > `.env.{APP_ENV}` > `.env` per existing bootstrap behavior.

- [ ] **Step 1: Add a failing API bootstrap-order regression**

The test must prove that security configuration is bootstrapped before importing router/security modules that create `SERVICE_KEY_STORE`.

Prefer a subprocess/import-isolation test or a small import-order helper test rather than relying on already-populated `os.environ` in the pytest process.

Required assertion:

```text
configured SRA_SERVICE_KEYS_FILE from bootstrap
→ api.security.service_key_store.SERVICE_KEY_STORE.path equals configured path
```

- [ ] **Step 2: Add a failing CLI bootstrap regression**

Call `api.security.cli.main()` with bootstrap setting `SRA_SERVICE_KEYS_FILE` to a temporary path and create a key.

Assert:

```text
key store is created at configured path
no default .sra_service_keys.json is created as a side effect of that CLI invocation
```

- [ ] **Step 3: Bootstrap before security/router imports in `api.main`**

Keep the change minimal. The effective ordering must be equivalent to:

```python
from config.bootstrap import bootstrap_env
bootstrap_env()

# only after this import modules that instantiate configuration-backed globals
from api.routers import ...
```

Do not add a second dotenv loader.

- [ ] **Step 4: Bootstrap inside CLI before `ServiceKeyStore()` construction**

`python -m api.security.cli ...` must honor the same environment-file semantics as the API.

Do not add service-key plaintext to command-line arguments.

- [ ] **Step 5: Add runtime-secret ignore coverage if needed**

From real `git status`, verify that `.env.local`, configured local auth stores, login-audit stores, service-key stores, pytest caches, and runtime logs cannot be accidentally staged.

Do not blindly ignore arbitrary source files. Keep `.env.example` tracked.

- [ ] **Step 6: Run targeted tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_security_env_bootstrap.py \
  tests/test_service_key_cli.py \
  tests/test_runtime_import_namespace.py
```

---

## Task 2: Centralize authenticated-or-capability access and enforce the exact signed query contract

**Files:**
- Modify: `sra_api/security/principal.py`
- Modify: `sra_api/routers/docs.py`
- Modify: `sra_api/routers/export.py`
- Modify if useful: `sra_api/security/signed_urls.py`
- Extend: `tests/test_signed_resource_urls.py`
- Extend: `tests/test_api_security_boundaries.py`
- Create if separation improves clarity: `tests/test_resource_capability_auth.py`

**Interfaces:**
- Add/use one shared helper named `require_principal_or_capability` (or the exact existing equivalent if the repository already added it).
- Valid bearer principal authorizes by required scope.
- No bearer header allows exact capability validation.
- Invalid bearer header never falls back to capability.
- Capability path returns whether capability auth was used so signed-response headers can be applied.

- [ ] **Step 1: Write failing duplicate/protected-query tests**

Cover signed access for:

```text
GET /v1/docs/{doc_id}
GET /v1/docs/{doc_id}/fulltext
GET /v1/export/word
```

At minimum reject capability requests containing:

```text
duplicate sig
duplicate format
duplicate download
duplicate text_layer
duplicate session_id
duplicate turn_id
unsupported representation value
additional security-sensitive/unsupported query key
```

Use the request multi-value API; do not test only normalized FastAPI arguments.

- [ ] **Step 2: Write failing cross-capability and Authorization-authority tests**

Prove:

```text
doc_detail sig cannot open fulltext
doc_fulltext sig cannot open detail
doc_id substitution fails
fulltext representation substitution fails
legacy Word turn/session substitution fails
invalid Authorization + otherwise-valid sig → 401 from invalid credential, no capability fallback
valid principal without required scope + valid sig → 403, no capability fallback
```

- [ ] **Step 3: Implement the shared resolver/helper**

The helper must:

1. receive the already-resolved optional principal;
2. if principal exists, enforce the required scope and return authenticated mode;
3. if principal is absent, validate query multiplicity/canonical values/allowed query keys;
4. validate the `sig` against the exact route/resource/representation binding;
5. return capability mode only after successful validation.

Do not perform resource lookup inside this helper.

- [ ] **Step 4: Route docs/fulltext/export through the shared helper**

Remove duplicated ad hoc capability logic only after equivalent tests exist.

Preserve authenticated direct-client compatibility:

```text
document:read → docs detail/fulltext
report:legacy-download → legacy Word
```

Authenticated direct legacy Word callers may retain missing-`turn_id` latest-turn compatibility. Capability callers must require precise `turn_id`.

- [ ] **Step 5: Add signed-resource response headers**

When access mode is capability, successful responses must include:

```text
Cache-Control: no-store
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```

Apply this consistently to:

```text
document detail JSON
document fulltext JSON
document fulltext TXT/download
legacy Word
```

Do not change payload/body formats beyond what is needed to attach headers.

- [ ] **Step 6: Run targeted route/capability tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_signed_resource_urls.py \
  tests/test_resource_capability_auth.py \
  tests/test_api_security_boundaries.py \
  tests/test_chat_word_export_metadata.py
```

If `tests/test_resource_capability_auth.py` is not created, run the equivalent expanded existing files.

---

## Task 3: Complete service-key correctness, administration tests, security audit, and leak prevention

**Files:**
- Modify: `sra_api/security/service_key_store.py`
- Modify: `sra_api/security/principal.py`
- Modify: `sra_api/routers/service_keys.py`
- Modify: `sra_api/routers/report_jobs.py`
- Reuse: `sra_api/services/editor_audit.py` unless current source already has a dedicated approved audit sink
- Extend: `tests/test_service_key_store.py`
- Extend: `tests/test_service_key_api.py`
- Extend: `tests/test_unified_principal.py`
- Extend/create: `tests/test_service_key_cli.py`
- Create/extend: `tests/test_security_audit.py`

**Interfaces:**
- Store boundary validates/normalizes metadata before persistence.
- HTTP/CLI never expose digest.
- Raw key only appears in create result once.
- Audit records contain safe identifiers/metadata only.

- [ ] **Step 1: Write failing expiration/metadata validation tests**

Cover:

```text
empty/whitespace-only key name rejected
unknown scope rejected
malformed expires_at rejected
timezone-naive expires_at rejected or normalized by one explicit documented rule
valid timezone-aware expires_at normalized consistently
expired key resolves to None, never raises TypeError/500
```

Keep the rule simple and deterministic; do not introduce a new external date library.

- [ ] **Step 2: Write failing real HTTP administration tests**

Use the actual service-key router dependency behavior.

Prove:

```text
superuser can create key
create returns raw key once
list omits raw key and token_digest
revoke succeeds and next credential resolution fails
non-superuser denied
service key cannot satisfy Editor superuser dependency
unknown scope → 422
```

- [ ] **Step 3: Write failing CLI tests**

Prove:

```text
create-service-key prints key once
list-service-keys omits raw key and token_digest
revoke-service-key revokes by key_id
configured store path is honored
CLI never requires raw secret as input argument
```

- [ ] **Step 4: Write corrupt-store and concurrent-process tests**

Corrupt store:

```text
malformed JSON → ServiceKeyStoreError
original corrupt file remains intact
operation does not overwrite it with an empty store
```

Cross-process mutation:

- use a cross-platform process strategy such as `multiprocessing.get_context("spawn")` or equivalent;
- create multiple independent keys against the same file;
- after all processes exit successfully, list count equals created count and every key ID is unique;
- no lost updates and JSON remains valid.

- [ ] **Step 5: Add unified authn/authz audit events**

Use the existing audit sink if suitable.

Record at minimum:

```text
authentication denied
authorization denied
service-key created
service-key revoked
admin cross-owner Report Job access
```

Safe fields may include:

```text
action
reason
principal kind
principal subject
required scopes
key_id
key name
assigned scopes
job_id
actor username
```

Never include:

```text
Authorization header
raw service key
token_digest
user bearer token
password/reset token
sig value
```

- [ ] **Step 6: Add leak regressions**

Assert raw/digest values are absent from:

```text
HTTP 401/403 bodies
service-key list response
CLI list output
audit records
captured logs/exceptions
```

- [ ] **Step 7: Run targeted service-key/audit tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_service_key_cli.py \
  tests/test_unified_principal.py \
  tests/test_security_audit.py
```

---

## Task 4: Harden Report Job version-0 → version-1 migration validation and failure injection

**Files:**
- Modify: `sra_api/services/report_job_store.py`
- Extend: `tests/test_report_job_migration_v1.py`
- Extend: `tests/test_report_job_store.py`
- Extend: `tests/test_job_authorization.py`

**Interfaces:**
- Migration ordering from Design v3 is immutable.
- Legacy `PRAGMA user_version=0` is the only accepted migration source.
- Canonical owner-aware schema is version 1.
- Version 1 must be validated on reopen, not trusted only by version number.

- [ ] **Step 1: Write failing legacy-schema validation tests**

Create version-0 DB variants with the same or similar columns but wrong constraints/indexes.

Reject at minimum:

```text
missing required column
extra/incompatible column
wrong job_id primary-key shape
missing required NOT NULL constraint
missing legacy global UNIQUE(idempotency_key)
legacy owner columns already present in an unknown shape
```

Unknown legacy shapes must fail before rename.

- [ ] **Step 2: Add explicit legacy/staged/canonical validator helpers**

Use SQLite metadata, not SQL string substring guessing where a PRAGMA is available.

Legacy validation must prove supported version-0 shape, including the old global idempotency uniqueness.

Staged validation must prove:

```text
same row count
every legacy job_id present
required non-null fields remain non-null
owner_kind/owner_id are NULL for migrated rows
```

Canonical validation must prove:

```text
expected version-1 columns/constraints
owner_kind and owner_id exist
no global single-column UNIQUE(idempotency_key)
owner-scoped unique index exists
index is unique
index is partial
index columns exactly owner_kind, owner_id, idempotency_key
row count preserved
```

- [ ] **Step 3: Validate already-version-1 databases on initialize/reopen**

`user_version == 1` must call canonical validation. A malformed version-1 DB must fail closed.

Fresh DB creation must also satisfy the same canonical validator before successful initialization.

- [ ] **Step 4: Replace post-step-only checkpoint tests with SQL-operation-boundary failure injection**

Introduce the smallest test seam around migration SQL execution if needed. Do not change migration ordering.

Inject `sqlite3.OperationalError` or equivalent at operations representing:

```text
copy INSERT ... SELECT
first rename
new canonical rename or owner index creation
DROP old table if useful
PRAGMA user_version set/verification
```

A test seam is acceptable only if production execution still executes the same SQL and the seam exists solely to inject operation failure.

- [ ] **Step 5: Reopen after every injected failure and prove full rollback**

After a failed `initialize()`, close and reopen the database and assert:

```text
user_version == 0
legacy report_jobs is canonical and usable
original rows unchanged
legacy global idempotency uniqueness still rejects duplicate key
owner_kind/owner_id absent
report_jobs_new absent
report_jobs_old absent
owner-scoped v1 index absent
```

- [ ] **Step 6: Add concurrent initialize regression**

Two concurrent initializers against one supported legacy DB must serialize under `BEGIN IMMEDIATE` and finish with one valid canonical version-1 database, not a mixed schema.

- [ ] **Step 7: Re-run Job authorization/idempotency tests**

Prove:

```text
same idempotency key allowed for two different owners
same owner + same key + same request returns existing job
same owner + same key + different request → 409 conflict
legacy NULL-owner job visible only to report:job:admin
unrelated principal receives 404 before metadata/status disclosure
admin cross-owner access is audited
```

- [ ] **Step 8: Run Job tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_report_job_migration_v1.py \
  tests/test_report_job_store.py \
  tests/test_job_authorization.py \
  tests/test_report_jobs_api.py \
  tests/test_report_jobs_lifecycle.py
```

---

## Task 5: Finish CORS, signing-secret policy, and public-route matrix

**Files:**
- Modify: `sra_api/main.py`
- Modify: `sra_api/security/signed_urls.py`
- Extend: `tests/test_security_cors.py`
- Extend: `tests/test_api_security_boundaries.py`
- Create/extend: `tests/test_security_startup.py`

**Interfaces:**
- Reuse `api.services.auth_support.PRODUCTION_ENVS`.
- Production with empty CORS list permits no cross-origin browser origin; server-to-server requests remain unaffected.
- Development wildcard, if retained, is not credentialed.
- Production signing secret is stable and at least 32 bytes.

- [ ] **Step 1: Write complete failing CORS matrix tests**

Cover:

```text
configured origin receives Access-Control-Allow-Origin
Authorization is allowed
Content-Type is allowed
Idempotency-Key is allowed
existing session headers remain allowed
unconfigured origin receives no allow-origin in production
empty production CORS list is not wildcard
wildcard development mode does not combine '*' with credentialed access
normal server-to-server request without Origin is unaffected
```

- [ ] **Step 2: Reuse the existing production environment constant**

Remove duplicated local `{"prod", "production"}` policy from CORS/security configuration and import/reuse `PRODUCTION_ENVS`.

- [ ] **Step 3: Add production signing-secret tests**

Prove:

```text
APP_ENV=production + missing secret → configuration/startup failure
APP_ENV=production + <32-byte secret → failure
APP_ENV=production + >=32-byte secret → accepted
```

Tests must not print the secret.

- [ ] **Step 4: Warn safely when non-production fallback is used**

If development/test fallback remains, emit one clear warning that a development signing secret/fallback is being used. The warning must not contain secret material.

Tests should inject an explicit deterministic secret where possible rather than depending on fallback.

- [ ] **Step 5: Add explicit public-route matrix**

Assert:

```text
/healthz public
/docs public
/openapi.json public
/redoc disabled
/v1/models protected
/v1/chat/completions protected
/v1/report/word protected
/v1/report/jobs protected
/v1/docs/{doc_id} protected-or-signed
/v1/docs/{doc_id}/fulltext protected-or-signed
/v1/export/word protected-or-signed
```

- [ ] **Step 6: Run CORS/startup/public tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_security_cors.py \
  tests/test_security_startup.py \
  tests/test_api_security_boundaries.py
```

---

## Task 6: Complete adversarial negative tests and OpenWebUI least-privilege integration

**Files:**
- Extend: `tests/test_agent_api_auth.py`
- Extend: `tests/test_api_security_boundaries.py`
- Extend: `tests/test_job_authorization.py`
- Extend: `tests/test_signed_resource_urls.py`
- Extend: `tests/test_service_key_api.py`

- [ ] **Step 1: Add authentication bypass regressions**

Prove none of these authenticate without a valid bearer credential:

```text
X-Session-Id
X-OpenWebUI-Chat-Id
X-Conversation-Id
Origin/CORS
known session_id
known turn_id
known job_id
```

- [ ] **Step 2: Add scope-escalation matrix**

At minimum:

```text
model:read cannot invoke chat
model:invoke cannot list models
OpenWebUI key (model:read + model:invoke) cannot create Report Job
Batch key (job create/read/download) cannot invoke chat unless explicitly granted
service key cannot list Editor users
service key cannot manage service keys
normal user cannot gain report:job:admin
```

- [ ] **Step 3: Add IDOR/path/query injection regressions**

Include quote characters, SQL metacharacters, Unicode, and traversal-like strings in:

```text
idempotency key
service-key name
metadata
filename
job-id URL
signed document query values
```

Expected: treated as data or rejected by validation; no SQL/path structure change.

- [ ] **Step 4: Add OpenWebUI least-privilege integration test**

Create one temporary service key with exactly:

```text
model:read
model:invoke
```

Verify:

```text
GET /v1/models → 200
POST /v1/chat/completions → 200 using a stubbed/controlled Agent execution boundary
POST /v1/report/jobs → 403
returned citation/Word URLs contain sig and work without Authorization
revoke key
next model request → 401
```

Do not call a real external LLM/Elasticsearch service in this regression; patch only the external execution boundary, not the auth logic being tested.

- [ ] **Step 5: Run adversarial security suite**

```bash
PYTHONPATH=. pytest -q \
  tests/test_agent_api_auth.py \
  tests/test_api_security_boundaries.py \
  tests/test_job_authorization.py \
  tests/test_signed_resource_urls.py \
  tests/test_service_key_api.py \
  tests/test_security_audit.py
```

---

## Task 7: Synchronize operational docs, `.codex` memory, and final Phase 0 gate

**Files:**
- Modify: `.env.example` only if behavior/wording changed
- Modify: `README.md`
- Modify: `docs/security/openwebui-service-key-setup.md`
- Modify: `docs/security/service-key-operations.md`
- Modify: `docs/security/sra-api-security-boundary.md`
- Modify: `docs/api/report-api.md`
- Modify: `docs/report_word_api_automation.md`
- Modify: `docs/operations/report-jobs.md`
- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/memory.md`
- Modify: `.codex/backlog.md`
- Modify: `.codex/known_issues.md`

- [ ] **Step 1: Remove obsolete `.env` workaround text after Task 1 passes**

The docs must no longer claim that the Service Key CLI does not load `.env` once that implementation is fixed.

Keep the distinction explicit:

```text
SRA_SIGNED_URL_SECRET = server-side URL signing secret
SRA_SERVICE_KEYS_FILE = path to service-key store, not a key
sra_sk_... = OpenWebUI/API bearer credential
```

- [ ] **Step 2: Add Authorization to all protected API examples**

Update tracked curl/JavaScript/Python examples for:

```text
/v1/report/word
/v1/report/jobs
/v1/models
/v1/chat/completions
```

Do not place real keys in docs. Use `sra_sk_<...>` placeholders or environment variables.

- [ ] **Step 3: Document signed query/logging policy**

State that `sig` is a bearer capability until expiry and query strings may be recorded by reverse-proxy/access logs. Recommend query-string redaction/omission for signed-resource routes where operationally practical.

- [ ] **Step 4: Update `.codex` files to current truth**

Do not leave contradictory statements saying Agent APIs remain public.

Move completed completion-audit items out of backlog only after tests prove them. Preserve future items:

```text
per-end-user OpenWebUI identity propagation
service-key rotation workflow
rate limits/quotas
Batch Scheduler / Server Dashboard / Windows GUI
```

- [ ] **Step 5: Run all targeted security/auth tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_runtime_import_namespace.py \
  tests/test_auth_store_security.py \
  tests/test_security_env_bootstrap.py \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_service_key_cli.py \
  tests/test_unified_principal.py \
  tests/test_security_audit.py \
  tests/test_agent_api_auth.py \
  tests/test_signed_resource_urls.py \
  tests/test_resource_capability_auth.py \
  tests/test_job_authorization.py \
  tests/test_report_job_migration_v1.py \
  tests/test_security_cors.py \
  tests/test_security_startup.py \
  tests/test_api_security_boundaries.py \
  tests/test_security_docs.py
```

If a proposed new test file was folded into an existing file, substitute the actual path; do not skip the behavior.

- [ ] **Step 6: Run affected API/Job regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/test_turn_execution_service.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_export_word_service.py \
  tests/test_report_jobs_api.py \
  tests/test_report_job_store.py \
  tests/test_report_job_worker.py \
  tests/test_report_jobs_lifecycle.py \
  tests/test_report_jobs_docs.py
```

- [ ] **Step 7: Run the complete repository test suite**

```bash
PYTHONPATH=. pytest tests -q --tb=short
```

Report exact pass/fail/error/warning counts.

- [ ] **Step 8: Run static/security verification**

```bash
python -m compileall sra_api api tests
git diff --check

rg -n 'from sra_api\.security|import sra_api\.security|sra_api\.services\.auth_store|sra_api\.routers\.editor_dependencies' sra_api tests api

rg -n 'Authorization.*print|print\(.*Authorization|token_digest.*(print|log)|sra_sk_[A-Za-z0-9_-]{12,}' sra_api tests docs .codex || true
```

Review matches manually; placeholder strings in docs/tests are allowed, real credentials are not.

- [ ] **Step 9: Verify runtime artifacts are not staged**

```bash
git status --short
git ls-files | rg '(^|/)(\.env$|\.env\.local$|\.sra_service_keys|\.auth_users|login_audit|sra-auth-log|__pycache__|\.pytest_cache)' || true
```

If a runtime file is intentionally tracked for fixtures, document why; otherwise remove it from the index/ignore it appropriately without deleting the operator's local data.

- [ ] **Step 10: Manual smoke gate**

Against a local/staging API with stable test configuration:

```text
no key:
  GET /v1/models → 401
  POST /v1/chat/completions → 401

OpenWebUI key (model:read + model:invoke only):
  GET /v1/models → 200
  POST /v1/chat/completions → success
  POST /v1/report/jobs → 403

Batch key:
  POST /v1/report/jobs → 202
  GET own job → 200
  GET another principal job → 404

signed browser links:
  citation detail/fulltext → success without Authorization
  Word → success without Authorization
  duplicate/tampered/substituted query or sig → rejected

revoked key:
  next protected request → 401

production config:
  missing/weak SRA_SIGNED_URL_SECRET → startup failure
  configured SRA_SERVICE_KEYS_FILE from env is the store actually used by API/CLI
```

- [ ] **Step 11: Completion report**

Codex must report:

```text
Repository
Branch
Baseline commit
Design version
Plan version
Changed files
Behavior changes
Tests executed
Exact test results
Deviations from Plan v4
Remaining issues/risks
```

Do not write “Phase 0 security gate passed” unless every required gate above is actually executed and successful.

---

# Rollout Checklist After Plan v4 Passes

- [ ] Back up auth state, service-key store, Job DB, and relevant report state.
- [ ] Set `APP_ENV=production`.
- [ ] Set stable `SRA_SIGNED_URL_SECRET` with at least 32 bytes of secret material.
- [ ] Set/verify `SRA_SERVICE_KEYS_FILE` at the intended persistent path.
- [ ] Use the CLI to create `openwebui-production` with only `model:read` + `model:invoke`.
- [ ] Confirm CLI and API are reading the same key store.
- [ ] Configure the key once in OpenWebUI Admin provider settings.
- [ ] Restart SRA API.
- [ ] Verify models/chat and signed citation/Word links.
- [ ] Verify anonymous protected calls return 401.
- [ ] Revoke temporary/test keys.
- [ ] Do not create/use a Batch key until Batch Scheduler implementation actually begins.
