# SRA Unified API Security Boundary — Implementation Review v1

## Baseline

- **Repository:** `poc-agent` source tree (remote repository URL not present in the supplied snapshot)
- **Branch:** unavailable in supplied ZIP; do not infer
- **Commit:** unavailable; supplied ZIP contains no `.git` metadata
- **Source baseline:** `poc-agent_20260902-203534.zip`
- **Design:** `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`
- **Prior plan:** `docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v3.md`
- **Prior Codex prompts:** `docs/superpowers/specs/2026-09-02-sra-security-boundary-codex-prompts-v3.md`
- **Review scope:** current Phase 0 implementation only

## Verdict

**NOT PASS — Phase 0 v3 is substantially implemented, but the security gate is not yet complete.**

The architecture in Design v3 remains valid and does **not** need a Design v4. The remaining work is implementation hardening, validation, audit coverage, test coverage, and configuration/bootstrap consistency. Continue with Plan v4 rather than redesigning the system.

## What is already implemented and should be preserved

The current baseline already contains the major Phase 0 structure:

- canonical runtime namespace protection around `api.*`;
- Editor auth dependency resolves mutable `AUTH_STORE` through `api.services.auth_store` rather than a stale captured singleton;
- `AuthPrincipal` and registered scope model;
- service-key format/store, SHA-256 digest persistence, in-process `RLock`, OS-level cross-process lock, atomic replace, create/list/revoke/resolve;
- superuser service-key routes and local CLI;
- `/v1/models`, `/v1/chat/completions`, sync Word, and Job routes have scope enforcement;
- owner-aware Report Job model, owner-scoped idempotency index, legacy version-0 to version-1 rebuild skeleton, and rollback transaction;
- HMAC signed-resource token generation and exact payload binding;
- signed citation/fulltext/legacy Word link generation;
- production signing-secret check in API lifespan;
- initial CORS hardening and public Swagger/ReDoc policy;
- Phase 0 security/OpenWebUI operational documentation.

These pieces are the implementation baseline. Codex must not delete/rebuild them merely because Plan v3 still contains unchecked tasks.

---

## Blocking issue 1 — security configuration bootstrap is not guaranteed before service-key singleton creation

**Location**

- `sra_api/main.py`
- `sra_api/security/principal.py`
- `sra_api/security/service_key_store.py`
- `sra_api/security/cli.py`
- `config/bootstrap.py`

**Problem**

`SERVICE_KEY_STORE = ServiceKeyStore()` is created at `api.security.service_key_store` import time. `api.main` imports `chat`, which imports `api.security.principal`, which imports the service-key store before `api.main` explicitly performs any security environment bootstrap. The CLI also constructs `ServiceKeyStore()` without first calling `bootstrap_env()`.

The documentation now states that `SRA_SERVICE_KEYS_FILE` may be supplied through `.env`, but the implementation does not provide one explicit, guaranteed bootstrap boundary before the service-key store path is frozen.

**Possible result**

- API can validate against the default `.sra_service_keys.json` while the operator believes it is using the path configured in `.env`.
- CLI can create a key in a different store than the API reads.
- OpenWebUI receives `401 Invalid credential` even though key creation succeeded.
- Production rollout becomes configuration-order dependent.

This is fail-closed rather than an authentication bypass, but it blocks a reliable production rollout.

**Required fix**

- Make API environment bootstrap explicit before importing routers/security modules that instantiate configuration-backed singletons.
- Make the service-key CLI call `bootstrap_env()` before constructing its store.
- Add regression tests proving API/CLI resolve the configured store consistently.
- After the fix, remove documentation that tells operators to work around the CLI `.env` inconsistency.

**Design/Plan impact**

- Design v3: **no change**.
- Plan: **update required** (Plan v4 Task 1).

---

## Blocking issue 2 — signed capability/query validation is incomplete relative to Design v3 §11.1

**Location**

- `sra_api/routers/docs.py:84-92, 94-97, 305-319`
- `sra_api/routers/export.py:92-105`
- `sra_api/security/signed_urls.py`

**Problem**

The current implementation checks duplicate `sig`, and fulltext partially checks `download`, but it does not enforce the complete canonical query contract across all signed-resource routes.

Missing/partial cases include:

- duplicate protected keys such as `format`, `text_layer`, `session_id`, and `turn_id`;
- route-level rejection of unsupported/additional security-sensitive query keys for capability access;
- one shared `require_principal_or_capability` path, as required by the approved design;
- consistent signed-resource response headers on document detail/fulltext responses.

`GET /v1/docs/{doc_id}` currently returns a normal dict after capability authentication and therefore does not add the signed-resource `Cache-Control`, `Referrer-Policy`, and `X-Content-Type-Options` headers. Fulltext likewise does not consistently apply all three headers.

**Possible result**

- ambiguous duplicate query parsing can diverge between FastAPI normalization and security validation;
- signed-resource routes do not fully satisfy the exact capability contract;
- future edits can cause docs/export authorization behavior to drift because each route has its own implementation.

**Required fix**

Implement one shared authenticated-or-capability helper and one canonical query validator, then route docs/fulltext/legacy Word through it. Capability validation must occur before resource lookup/serialization. Add the required response headers whenever capability access is used.

**Design/Plan impact**

- Design v3: **no change**.
- Plan: **update required** (Plan v4 Task 2).

---

## Blocking issue 3 — Report Job migration checks are not yet strong enough for the approved rebuild contract

**Location**

- `sra_api/services/report_job_store.py:_migrate_v0()`
- `tests/test_report_job_migration_v1.py`

**Problem**

The exact rename/index/drop/version ordering is now correct, but validation/test depth is incomplete:

- supported legacy schema validation currently compares only column names and does not prove legacy NOT NULL/PK/global idempotency uniqueness constraints;
- staged validation does not explicitly verify required non-null values;
- canonical validation does not explicitly prove the old global `idempotency_key` uniqueness is absent or that the new index is partial with the expected predicate/shape;
- opening an already-version-1 database does not validate canonical schema before accepting it;
- current rollback tests inject failures through post-step checkpoints rather than at the SQL operation boundary;
- current rollback tests do not explicitly prove that `report_jobs_new` / `report_jobs_old` are absent after reopen;
- concurrent initialize/reopen behavior is not tracked as a regression test.

**Possible result**

An unexpected version-0 database with the same column names but different constraints can be migrated as though it were the supported legacy schema. A malformed version-1 database can also be accepted solely because `user_version == 1`.

**Required fix**

Add explicit legacy/staged/canonical schema validators, validate version-1 on reopen, and move failure injection to the actual migration SQL execution boundary. Reopen the DB after each injected failure and verify the entire legacy state.

**Design/Plan impact**

- Design v3: **no change**.
- Plan: **update required** (Plan v4 Task 4).

---

## Major issue 1 — required Phase 0 security audit events are not implemented at the unified boundary

**Location**

- `sra_api/security/principal.py`
- `sra_api/routers/service_keys.py`
- `sra_api/routers/report_jobs.py`
- existing reusable audit sink: `sra_api/services/editor_audit.py`

**Problem**

Design v3 requires audit records for service-key create/revoke, authentication denied, authorization denied, and administrative cross-owner Job access. The unified principal/service-key code currently emits none of these events.

**Required fix**

Reuse the existing audit sink rather than introducing a parallel logging architecture unless the existing sink proves unsuitable. Record only safe metadata such as principal kind/subject, required scopes, key ID/name/scopes, action/reason, and Job ID. Never record Authorization, raw service keys, stored digests, user bearer tokens, passwords, reset tokens, or signed capability values.

**Design/Plan impact**

- Design v3: **no change**.
- Plan: **update required** (Plan v4 Task 3).

---

## Major issue 2 — service-key API/CLI/store validation and regression coverage are too shallow

**Location**

- `sra_api/security/service_key_store.py`
- `sra_api/security/cli.py`
- `sra_api/routers/service_keys.py`
- `tests/test_service_key_store.py`
- `tests/test_service_key_api.py`
- `tests/test_unified_principal.py`

**Problem**

Current tracked tests prove only a small subset of the approved contract. They do not prove:

- HTTP superuser-only create/list/revoke behavior;
- service keys cannot administer Editor users/service keys;
- CLI create/list/revoke behavior and no secret/digest leakage;
- invalid/revoked/expired service keys fail as `401` without raising internal exceptions;
- malformed/corrupt store fails closed and is preserved;
- concurrent process mutations do not lose updates;
- `expires_at` is validated/normalized before `resolve()` compares timestamps.

`expires_at` is currently stored as arbitrary text. A timezone-naive or malformed value can raise during comparison with timezone-aware `now`.

**Required fix**

Validate and normalize service-key metadata at the store boundary, then add real HTTP/CLI/concurrency/corruption/leak tests.

---

## Major issue 3 — CORS/production-secret tests do not prove the approved policy

**Location**

- `sra_api/main.py`
- `sra_api/security/signed_urls.py`
- `tests/test_security_cors.py`

**Problem**

`tests/test_security_cors.py` currently performs only one broad assertion. It does not prove configured-origin preflight, production empty-origin behavior, required request headers, server-to-server independence, or the public docs matrix. `main.py` also duplicates `{"prod", "production"}` instead of reusing `PRODUCTION_ENVS` as required by the plan/design.

The development fallback signing secret is silent; the approved design requires any non-production fallback to be clearly warned without printing the secret.

**Required fix**

Reuse the existing production environment definition, add explicit CORS matrix tests, and add production missing/weak signing-secret startup/config tests plus a safe non-production fallback warning test.

---

## Major issue 4 — tracked negative/leak/integration tests do not match the completion claims in project memory

**Location**

- `.codex/memory.md`
- `.codex/backlog.md`
- `tests/test_agent_api_auth.py`
- `tests/test_job_authorization.py`
- `tests/test_api_security_boundaries.py`
- `tests/test_signed_resource_urls.py`

**Problem**

`.codex/memory.md` records a prior “57 passed / 29 passed / 305 passed” completion claim and mentions concurrent-process/migration/manual smoke checks. However, the current tracked tests are materially thinner than the approved Plan v3 Task 11/12 requirements. `.codex/backlog.md` correctly records that the completion audit found missing negative/leak/API/CLI coverage.

The source and tracked tests are authoritative for this review. Do not treat the old memory completion statement as proof that the current Phase 0 gate is complete.

**Required fix**

Add the missing tracked regressions and update `.codex/memory.md` only after fresh verification.

---

## Minor issue 1 — source snapshot contains runtime/test artifacts that must not enter version control

The supplied ZIP contains items such as runtime auth/audit files, `sra-auth-log`, `.pytest_cache`, and `__pycache__`. The snapshot has no `.git` metadata, so this review cannot determine whether they are tracked or merely local/untracked.

Codex must inspect real `git status` before editing. Do not stage runtime auth/audit/key files. Ensure `.env.local` and the actual configured local auth/audit runtime paths are ignored where appropriate, while keeping `.env.example` tracked.

---

## Verification performed during this review

The supplied analysis environment does not contain the `elasticsearch` Python package, so tests that import the complete API app cannot be collected here. This is an environment limitation, not evidence that those tests pass or fail in the real repository environment.

Fresh checks on this source snapshot:

```text
python -m compileall -q sra_api api tests
→ exit 0 (one existing SyntaxWarning in docx/table.py)

canonical namespace rg guard
→ no matches

PYTHONPATH=. pytest -q tests/test_security_docs.py
→ 2 passed

PYTHONPATH=. pytest -q tests/test_runtime_import_namespace.py
→ 1 passed

PYTHONPATH=. pytest -q tests/test_service_key_store.py
→ 1 passed

PYTHONPATH=. pytest -q tests/test_service_key_api.py
→ 1 passed

PYTHONPATH=. pytest -q tests/test_unified_principal.py
→ 2 passed

PYTHONPATH=. pytest -q tests/test_signed_resource_urls.py
→ 2 passed

PYTHONPATH=. pytest -q tests/test_report_job_migration_v1.py
→ 5 passed

PYTHONPATH=. pytest -q tests/test_report_job_store.py
→ 3 passed
```

A larger targeted run reached `28 passed` before/alongside failures caused by missing `elasticsearch`; full API-related test collection is therefore **not verified** in this review environment.

## Version decision

- **Design v3:** remains authoritative; **no Design v4**.
- **Plan v3:** mostly implemented; superseded for remaining Phase 0 work by **Plan v4**.
- **Codex prompts v3:** superseded for continuation work by **Codex prompts v4**.
- Phase 0 may be marked PASS only after Plan v4 completion and a fresh implementation review/security gate.
