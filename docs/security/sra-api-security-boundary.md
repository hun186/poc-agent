# SRA API Security Boundary

Phase 0 protects Agent and report operations with one strict Bearer resolver. Editor user tokens remain user credentials; independently generated `sra_sk_` service keys resolve to scoped service principals and never authorize Editor administration.

| Endpoint | Authorization |
|---|---|
| `GET /v1/models` | `model:read` |
| `POST /v1/chat/completions` | `model:invoke` |
| `POST /v1/report/word` | `report:sync` |
| Report Job create/read/download | corresponding `report:job:*` scope plus owner check |
| Document and legacy Word GET | direct read scope or exact HMAC capability |
| `/healthz`, `/openapi.json`, `/docs` | public |

Signed URLs are bearer capabilities until expiry. They bind method, resource identifier, representation, and (for Word) exact turn. Access logs should omit or redact query strings so `sig` values are not retained.

Production requires a stable `SRA_SIGNED_URL_SECRET` of at least 32 bytes. Configure explicit `CORS_ALLOWED_ORIGINS`; CORS is not authentication.

