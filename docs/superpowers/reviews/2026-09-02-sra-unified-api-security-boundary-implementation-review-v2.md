# SRA Unified API Security Boundary — Implementation Review v2

## Historical status

**NOT PASS.** This historical review preceded Implementation Review v3 and evaluated the Phase 0 implementation against Design v3. Its repository-completion findings were carried forward into Plan v6 and subsequently Plan v6.1.

## Baseline and authority

- Design v3 remained authoritative; no Design v4 was required.
- Actual source, rather than stale plan paths, was the implementation baseline.
- Repository automation could not replace deployment acceptance using the real Elasticsearch and long-running report Agent path.

## Findings carried forward

The review required completion evidence for the following security properties:

1. Unified authentication and authorization denials must be safely audited without credential material.
2. Service Key create/revoke administration must be audited, and non-superuser administration must return 403 through the actual HTTP routes.
3. Cross-process Service Key persistence must remain atomic and must never persist raw keys.
4. Report Job schema initialization/migration must remain concurrency-safe and rollback-safe.
5. Signed-resource capabilities must reject duplicate, non-canonical, substituted, or extra parameters, and an invalid Authorization header must never fall back to capability authorization.
6. Successful signed resources must return `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Content-Type-Options: nosniff`.
7. Production signing configuration must fail closed when its secret is missing or weak, without disclosing secret values.
8. Production CORS and the canonical `api.*` runtime import namespace must remain hardened.
9. A fast route-level scope matrix may mock only the downstream Agent seam.
10. Final deployment acceptance must execute the real chain: Service Key authentication, report/analysis routing, Elasticsearch retrieval with source evidence, long-running Agent synthesis, final report, signed Word GET without Authorization, and a valid DOCX.

## Deployment disposition

The mandatory real Elasticsearch → long Agent → signed Word E2E was not established by repository-only tests. Existing working acceptance credentials were therefore to remain unchanged until that E2E passed; post-pass rotation and removal of literal credentials from the operator harness remained pending.

## Historical note

This file restores the v2 traceability location that was absent from the later repository snapshot. Review v3 is the authoritative review for the final completion delta and records which v2 findings had already been completed and which remained.
