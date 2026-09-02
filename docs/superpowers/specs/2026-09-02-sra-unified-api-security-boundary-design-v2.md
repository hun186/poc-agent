# SRA Unified API Security Boundary — Design Specification

**Date:** 2026-09-02  
**Target baseline:** `poc-agent(7)`  
**Scope:** Phase 0 Security Foundation only  
**Revision:** v2 — incorporates pre-implementation Codex security review

## 1. Purpose

The current SRA service already has an Editor authentication/RBAC system, but several agent-facing routes are intentionally public for OpenWebUI compatibility. That creates an authentication bypass: any network client that can reach port 9002 can invoke the Agent directly without first authenticating through OpenWebUI.

This phase establishes one unified security boundary for SRA APIs before building the Batch Scheduler, Windows GUI, or Server Management Dashboard.


## 1.1 Mandatory precondition: canonical runtime import namespace

Before adding any new security singleton/state, stabilize the existing Editor authentication import boundary.

The repository physically stores runtime code under `sra_api/`, but production/runtime compatibility imports are exposed through the `api.*` namespace. Loading the same stateful module through both names can create two Python module objects and therefore two independent module-level singletons.

**Canonical decision for Phase 0:**

```text
Runtime/stateful namespace = api.*
```

Rules:

- runtime code MUST import stateful auth/security modules through `api.*`;
- new security modules are physically stored under `sra_api/security/` but imported as `api.security.*`;
- do not mix `api.services.auth_store` and `sra_api.services.auth_store` in one runtime process;
- migrate tests that import stateful routers/auth modules through `sra_api.*` to `api.*`;
- pure stateless utility imports may be handled separately, but no mutable singleton may be reachable through two module identities;
- `editor_dependencies.py` MUST NOT capture `AUTH_STORE` by value with `from ... import AUTH_STORE`; it should resolve `auth_store_module.AUTH_STORE` at call time so a controlled module reload does not leave a stale singleton reference.

Add regression coverage that proves the application does not load duplicate stateful auth/security modules and that the Editor auth suite passes both standalone and combined with the security-boundary suite.


## 2. Current security baseline

Existing Editor authentication provides:

- signed user bearer tokens;
- user status checks;
- token version invalidation;
- denylist/revocation;
- role hierarchy:
  - `data_reader`
  - `data_editor`
  - `db_operator`
  - `superuser`
- login throttling;
- security/audit events;
- `require_role()` dependencies.

Current public agent/resource routes include at least:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /v1/docs/{doc_id}`
- `GET /v1/docs/{doc_id}/fulltext`
- `GET /v1/export/word`

The current Job API is also not protected by a unified principal dependency.

The test suite explicitly preserves some of those public boundaries, so those tests must be replaced with the new security contract rather than silently deleted.

## 3. Security goals

1. A client cannot invoke model/report/job APIs merely because it can reach port 9002.
2. OpenWebUI uses one administrator-configured SRA service key. Individual OpenWebUI users do not manage or receive that key.
3. Automated Batch Scheduler processes use their own independently revocable service key.
4. Human users can continue using existing Editor bearer tokens.
5. Service keys and human tokens resolve into one internal principal model.
6. Authorization happens at the server API boundary, not only in GUI visibility rules.
7. Job resources are owner-bound to prevent one principal reading another principal's jobs.
8. Browser-clickable Word/citation links never expose the OpenWebUI service key.
9. Secrets are never persisted or logged in plaintext.
10. Existing Editor RBAC remains compatible and service keys cannot authenticate to Editor administrator routes.
11. SQL queries affected by this change remain parameterized; request input is never interpolated into SQL identifiers or statements.
12. The implementation fails closed on missing, invalid, expired, or revoked credentials.

## 4. Non-goals

This phase does **not** implement:

- CSV/Excel/JSON Batch Scheduler;
- Windows GUI;
- Server Batch Dashboard;
- Redis/Celery/RQ/Kafka;
- distributed identity federation;
- per-OpenWebUI-user identity propagation;
- OAuth/OIDC;
- automatic service-key rotation;
- high-availability authentication storage;
- job retry/cancel UI.

Those build on this boundary later.

## 5. Principal model

Introduce an internal `AuthPrincipal` that is transport-neutral.

Suggested shape:

```python
@dataclass(frozen=True)
class AuthPrincipal:
    kind: Literal["user", "service"]
    subject: str
    role: str | None
    scopes: frozenset[str]
    credential_id: str | None = None
```

Examples:

```text
user:bruce
service:openwebui-production
service:batch-scheduler-01
```

The existing `AuthUser` and Editor `current_user()` remain valid for Editor routes. Service keys must not become valid Editor-user credentials.

## 6. Authentication resolver

`Authorization: Bearer <credential>` is the common transport.

Resolution:

1. Parse Bearer header strictly.
2. If token begins with `sra_sk_`, resolve it as a service API key.
3. Otherwise resolve it using the existing signed user-token logic.
4. Return `AuthPrincipal`.
5. Missing/invalid/revoked/expired credential → `401`.
6. Valid principal without required scope → `403`.

Do not infer authorization from:

- source IP;
- CORS;
- presence of OpenWebUI-specific headers;
- session ID;
- filename;
- job ID.


### 6.1 Optional principal and authenticated-or-capability resolution

Resource endpoints that support either authenticated direct access or a signed browser capability MUST NOT use a dependency that immediately returns `401` merely because the `Authorization` header is absent.

Provide two explicit interfaces:

```python
optional_principal(...) -> AuthPrincipal | None
require_principal_or_capability(...)
```

Contract:

- no `Authorization` header → `optional_principal()` returns `None`;
- malformed/invalid/revoked/expired `Authorization` header → `401`;
- valid header with insufficient scope → `403`;
- only when the header is absent may the resource resolver validate the signed capability;
- if an invalid Authorization header and a valid capability are both supplied, reject the invalid credential rather than silently falling back to the capability;
- the capability must be validated against the exact route/resource/representation binding before any resource lookup or response serialization.

## 7. Service API keys

### 7.1 Format

Generate at least 256 bits of cryptographically random secret material.

Suggested externally visible form:

```text
sra_sk_<key_id>_<random_secret>
```

`key_id` is a public lookup identifier. The random secret is shown exactly once.

### 7.2 Storage

Use a dedicated service-key store following the existing atomic JSON-store pattern.

Default file:

```text
.sra_service_keys.json
```

Configurable via:

```text
SRA_SERVICE_KEYS_FILE
```

Persist:

- `key_id`
- `name`
- `token_digest`
- `scopes`
- `status`
- `created_at`
- `created_by`
- `expires_at`
- `revoked_at`
- `revoked_by`
- safe display hint / last characters

Never persist the plaintext key.

Because generated keys have high entropy, store a SHA-256 digest of the complete service key and verify with constant-time comparison. Do not log the credential.


### 7.2.1 Cross-process mutation locking

The local CLI and running API may mutate the same service-key file concurrently. Atomic `os.replace()` publication alone is not sufficient because two processes can both read the same old state and overwrite one another.

Use one lock file derived from the service-key store path and hold an OS-level exclusive lock across the complete:

```text
read → validate/normalize → mutate → fsync/write temp → atomic replace
```

transaction.

Requirements:

- in-process `RLock`;
- inter-process OS advisory lock;
- POSIX implementation may use `fcntl.flock`;
- Windows implementation may use `msvcrt.locking` or an equivalent stdlib-backed abstraction;
- lock is released automatically when the file descriptor closes/process exits;
- store, lock, temp and recovery/backup files are owner-only where the OS supports POSIX permissions;
- corrupted/malformed store data MUST fail closed and preserve the original file; it must never be normalized to an empty key store and then overwrite the corrupt source;
- HTTP/admin outputs, logs, audit records, exceptions and object `repr` MUST NOT expose either raw keys or stored digests.

The persistence file and its protected filesystem backup necessarily contain the digest used to authenticate high-entropy service keys. This digest is not returned through normal API/CLI listing surfaces.

### 7.3 Service-key administration

Superuser-only endpoints:

```text
POST /v1/auth/service-keys
GET  /v1/auth/service-keys
POST /v1/auth/service-keys/{key_id}/revoke
```

Creation returns the plaintext secret once. Listing never returns it.

Also provide a local CLI so an administrator can generate a key before restarting the newly protected service:

```text
python -m api.security.cli create-service-key \
  --name openwebui-production \
  --scope model:read \
  --scope model:invoke
```

The CLI must never require a secret on the command line.

## 8. Scope registry

Initial scopes:

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

Only registered scopes may be assigned.

Recommended keys:

### OpenWebUI production

```text
model:read
model:invoke
```

No batch/admin scopes.

### Batch Scheduler

```text
report:job:create
report:job:read
report:job:download
```

Do not share the OpenWebUI key.

### Human users

Map active Editor users to agent/report scopes so future authenticated browser/Windows clients can operate as users. Initially all active roles may receive normal self-service model/report scopes; `superuser` additionally receives administrative job access. Keep Editor data-mutation authorization governed by the existing role checks.

## 9. Endpoint authorization matrix

### Public

Keep public only where authentication is required to bootstrap or where no sensitive operation occurs:

```text
GET  /
GET  /healthz
GET  /openapi.json
GET  static/login/editor shell assets

POST /v1/auth/login
POST /v1/auth/register
password recovery endpoints required by existing auth flow
```

### User-only existing Editor routes

Continue to use current Editor `current_user()` / `require_role()`.

Service keys must not satisfy these dependencies.

### Protected by unified principal/scopes

```text
GET  /v1/models
  → model:read

POST /v1/chat/completions
  → model:invoke

POST /v1/report/word
  → report:sync

POST /v1/report/jobs
  → report:job:create

GET /v1/report/jobs/{job_id}
  → report:job:read + owner check

GET /v1/report/jobs/{job_id}/word
  → report:job:download + owner check
```

### Resource routes that support authenticated access OR signed capability URL

```text
GET /v1/docs/{doc_id}
GET /v1/docs/{doc_id}/fulltext
GET /v1/export/word
```

Direct API clients use authenticated scopes:

```text
document:read
report:legacy-download
```

OpenWebUI browser clicks use signed URLs generated by the authenticated chat response.

## 10. Job ownership

The current Job API must become owner-aware.

Add:

```text
owner_kind
owner_id
```

to job persistence.

On creation:

```text
owner_kind = principal.kind
owner_id   = principal.subject
```

Status/download:

- owner can access;
- superuser / `report:job:admin` can access any;
- unrelated principal receives `404` rather than revealing that another principal's job exists.

Existing pre-migration jobs with no owner become legacy/unowned and are accessible only to superuser / job-admin principals.


### 10.1 SQLite migration is an explicit table rebuild

The current schema uses column-level `idempotency_key TEXT UNIQUE`; owner-scoped uniqueness cannot be achieved by merely adding owner columns.

The migration MUST use a versioned table rebuild under one transaction:

1. `BEGIN IMMEDIATE`;
2. create the new table with nullable `owner_kind` / `owner_id` for migrated legacy rows;
3. copy every existing row;
4. create a partial unique index equivalent to:

```sql
CREATE UNIQUE INDEX ... ON report_jobs(owner_kind, owner_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;
```

5. validate copied row count and required schema;
6. drop/rename old/new tables;
7. update schema version;
8. commit.

Migration tests MUST prove rollback leaves the old database usable if any step fails.

`owner_kind` / `owner_id` are NOT exposed to an unrelated caller before authorization. Router/service authorization must occur before returning `_view()`, metadata, artifact state or error detail that confirms the job exists.

### Idempotency isolation

Idempotency must be scoped by owner:

```text
(owner_kind, owner_id, idempotency_key)
```

Do not allow one principal's idempotency key to reveal another principal's job.

All SQLite operations remain parameterized.

## 11. Signed browser resource URLs

OpenWebUI server-to-server requests can carry the service key, but users clicking links in their browser cannot and must not receive that key.

Generate signed capability URLs for:

- citation document detail/fulltext links;
- legacy Word export links returned in chat responses / rendered Markdown.

Use HMAC-SHA256 with a dedicated secret:

```text
SRA_SIGNED_URL_SECRET
```

Production requires a stable secret of at least 32 bytes.

Config:

```text
SRA_SIGNED_URL_TTL_SECONDS
```

Recommended default:

```text
86400
```

(24 hours; configurable according to operational needs.)

Signed token must bind at least:

- version;
- HTTP method;
- resource type;
- exact resource identifier(s);
- allowed representation/options where relevant;
- expiry.

A token for one document/session/turn must not be reusable for another.

Anyone possessing a signed URL can use it until expiry, so it is a bearer capability. Do not place service keys or user tokens inside the URL.

Expired/tampered token → `401` or `403` without revealing sensitive validation details.


### 11.1 Canonical capability/query contract

Use a single query parameter named:

```text
sig
```

whose value is the complete signed capability envelope. The signed payload contains expiry; do not require a second unsigned `exp` parameter.

Each capability binds an exact resource action.

Document detail:

```text
resource_type = doc_detail
doc_id
method = GET
```

Document fulltext additionally binds:

```text
resource_type = doc_fulltext
doc_id
format = json | txt
download = 0 | 1
text_layer = reference | raw | both
method = GET
```

The five current browser-facing document variants therefore receive separate capabilities. A `doc_fulltext` capability MUST NOT authorize `/v1/docs/{doc_id}` detail access, and a detail capability MUST NOT authorize fulltext.

Legacy Word browser capability binds:

```text
resource_type = legacy_word
session_id
turn_id
method = GET
```

For browser-facing signed Word URLs, `turn_id` is REQUIRED and resolved before signing. The historical "missing turn_id means latest turn" behavior remains available only to an authenticated direct client with `report:legacy-download`.

Capability validation MUST reject:

- duplicate `sig`;
- duplicate protected query keys;
- non-canonical boolean aliases (signed browser URLs use only `0` or `1`);
- representation-changing values that differ from the signed payload;
- unsupported values or additional security-sensitive query parameters.

Use the request query multi-value API when checking duplicates; do not normalize duplicates away before validation.

Successful signed-resource responses SHOULD include:

```text
Cache-Control: no-store
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```

Signed URLs are bearer capabilities and are not individually revocable before expiry. Keep the TTL bounded.

### 11.2 Existing document-detail disclosure contract

`GET /v1/docs/{doc_id}` currently returns the complete Elasticsearch `_source`. Phase 0 preserves this behavior for compatibility, but treats it as a distinct `doc_detail` capability.

This is an explicit security decision, not an accidental inheritance from `doc_fulltext`.

Tests MUST prove:

- fulltext capability cannot open detail;
- detail capability cannot be substituted to another `doc_id`;
- authenticated `document:read` direct clients retain existing behavior.

A future hardening phase may introduce a reduced safe document presenter if the full `_source` is not required by operations.


## 11.3 Production signing-secret policy

Reuse the existing application environment semantics from `api.services.auth_support`:

```text
PRODUCTION_ENVS = {"prod", "production"}
```

Do not create a second definition of "production".

In production:

- `SRA_SIGNED_URL_SECRET` is mandatory;
- decoded/encoded secret strength must represent at least 32 bytes of secret material;
- missing/weak secret prevents application startup;
- no generated fallback is allowed.

In development/test:

- tests should inject a deterministic secret;
- an ephemeral fallback may be allowed only with a clear warning;
- the generated secret must never be logged;
- production-like environments must never fall back.

## 12. OpenWebUI integration

OpenWebUI administrator configures the SRA provider once:

```text
Base URL:
http://192.168.0.133:9002/v1

API Key:
sra_sk_<openwebui key>
```

OpenWebUI then sends:

```http
Authorization: Bearer sra_sk_...
```

for `/v1/models` and `/v1/chat/completions`.

Individual OpenWebUI users:

- do not configure a key;
- do not know the service key;
- continue to be authorized by OpenWebUI to use the model.

SRA audit sees the direct caller as the OpenWebUI service principal. Per-end-user identity propagation is deferred to a later phase.

## 13. CORS

CORS is not authentication.

Harden current configuration:

- same-origin Editor remains supported;
- server-to-server OpenWebUI calls are unaffected by browser CORS;
- in production, empty `CORS_ALLOWED_ORIGINS` means no cross-origin browser origins rather than wildcard;
- never combine wildcard origins with credentialed browser access;
- explicitly allow required headers such as `Authorization`, `Content-Type`, `Idempotency-Key`, and existing session headers.

Tests must cover CORS preflight for protected browser clients.


## 13.1 Swagger/OpenAPI route policy

Distinguish the API documentation UI from document-resource APIs:

```text
/v1/docs/{doc_id}   = protected document resource
/docs               = FastAPI Swagger UI
/openapi.json       = OpenAPI schema
/redoc              = ReDoc UI
```

Phase 0 policy:

- `/openapi.json` remains public;
- `/docs` remains public for operator/developer convenience;
- protected endpoints shown by Swagger still require credentials;
- `/redoc` is explicitly disabled unless the existing deployment has a documented operational dependency on it.

The separate existing Swagger static-asset rendering issue is not part of this security phase unless implementation changes touch those routes.

## 14. Audit/security logging

Audit:

- service-key created;
- service-key revoked;
- authentication denied;
- authorization denied;
- administrative cross-owner job access;
- security configuration failure at startup where applicable.

Never log:

- Authorization header;
- plaintext service key;
- signed user bearer token;
- password/reset token.

Sanitize errors so credential material cannot appear in responses.

Because signed capabilities are carried in the query string, deployment documentation MUST warn that reverse-proxy/access logs can record `sig`. Configure production proxy logging to redact/omit query strings for signed-resource routes where practical. Application code must not emit debug prints of Authorization headers or signed capability values.

## 15. Deployment and migration

Recommended zero-surprise rollout:

1. Back up `.sra_users.json`, job DB, and relevant state.
2. Deploy code.
3. Before restarting the protected API, use the local CLI to create:
   - `openwebui-production`
   - optionally a batch test key.
4. Configure the OpenWebUI administrator connection with the new key.
5. Configure stable `SRA_SIGNED_URL_SECRET`.
6. Restart SRA API.
7. Verify:
   - no-key `/v1/models` → `401`;
   - OpenWebUI key `/v1/models` → `200`;
   - OpenWebUI chat works;
   - citation/Word signed links work from the browser;
   - revoked key → `401`;
   - insufficient-scope key → `403`.
8. Remove any temporary test keys.

Do not introduce a permanent "public compatibility" bypass. If a development-only migration switch is unavoidable, it must default to secure/enforced behavior and be rejected in production unless explicitly documented and tested.

## 16. Security acceptance criteria

- Public direct invocation of Agent routes is no longer possible.
- OpenWebUI works with one admin-configured service key.
- Users do not receive the service key.
- Service key plaintext appears only once at creation.
- Revoked/expired key is rejected.
- Scope enforcement returns 403 on valid-but-insufficient principals.
- Service keys cannot access Editor admin APIs.
- Jobs are owner-isolated.
- Idempotency is owner-scoped.
- Browser citation/Word links work without exposing service/user credentials.
- Tampered/expired signed URLs fail closed.
- Signed fulltext/detail capabilities are representation-specific and non-substitutable.
- Browser signed Word URLs always bind an exact `turn_id`.
- Existing Editor RBAC tests still pass.
- No string-interpolated SQL is introduced.
- Security-boundary regression tests explicitly fail if protected routes become public again.
