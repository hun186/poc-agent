# Architecture and Engineering Decisions

## Current Summary

### Core authority and security

- Preserve SRAF core `sra_api/` (with `api/` compatibility), real Agent/LLM/ES/DOCX, existing Auth/RBAC/owner isolation, signed browser resources and audit. Do not build another auth store, scheduler, report worker or fake data authority.
- SQL Server remains Requirement Import Set/Version/Snapshot authority; `sra_schedule` owns recurring Schedule Versions, Handoff leases and transactional lifecycle/fencing. API lifespan owns Report Job Worker. SQL transactions do **not** atomically include HTTP/ES/filesystem writes.
- Product Task creation/provision and draft activation are superuser-only; service keys may execute only authorized provisioned Tasks. Canonical idempotency binds principal/operation/route/target IDs and semantic payload digest, including empty-body Task Run; same key/different target is conflict. Provisioning hides incomplete state; one-time initial Run and recurring enablement are released atomically with visible Task finalization. Schedule-affecting PATCH drafts are activated by a separate authorized action; no automatic proposal activation. Task/Version/Snapshot revisions use CAS owner fences. Product UI/HTTP and live SQL acceptance require independent verification.
- Release provenance uses reviewed package/runtime files and bounded runtime input discovery; the selected deployment-local Requirement SQL registry is not release-managed, does not enter a manifest and must not have contents/path/digest/credentials leaked. Release mode strictly fails on drift; functional mode can advise on reviewed byte mismatch only; module shadowing/unreviewed active inputs always fail closed.
- OFF-0/1 operator probes are **partial** evidence; no FULL_LIVE/physical airgap without true authorized Linux, ES, SQL, LLM, Report Job, Worker and DOCX verification. Strict CA/IP SAN identity is the trust default; diagnostic SAN WARN must remain lower assurance and is never equivalent to strict authenticated identity or TLS release acceptance.
- Protected local credential-bearing HTTP checks require verified listener/process ownership before sending bearer. OFF-1S must enumerate per-thread FD tables, bounded /proc mount visibility including nested overlays and repeated pre/post socket proof; still not cryptographic authentication.
- Operator preflight is never normal API startup: only superuser-triggered E2E source/Worker/root/LLM/ES readiness can stage a Plan. Apply the 540s *cooperative* deadline, bounded provider/ES per-call limits and no retry, distinguish RUNNING_OVERDUE from actual terminal TIMEOUT, never claim hard SDK cancellation. ES acceptance fixture uses dedicated index ownership, exact IDs/full sources/count, create-only missing-doc recovery and no automatic deletion/rollback.
- E2E Plan is immutable **per API process**, not a cluster capability. A new candidate stays request-local until whole operator evidence succeeds. On rerun, suspend new E2E Job admission and re-probe the same policy; drift/failure/timeout does not revive old trust or silently downgrade to mocks. Already-admitted verified E2E jobs keep the original pinned Plan, including smolagents tool threads; ordinary production jobs always follow real backends.
- Linux same-host, same-UID private `flock` serializes operator preflights but is not a distributed lock. **PR #328 pending:** a new operator check rotates a non-secret generation in the preflight lock under exclusive guard; new E2E admissions compare generation and reject other Workers' stale plans. Never export Plan JSON or pretend a peer's successful check authorizes another Worker. Different hosts/mounts/UIDs still require a future durable distributed design.

## Recent Decisions

- 2026-10-30: Retain per-Job pinned Plan instead of interrupting already-admitted reports on operator revalidation; do not infer partial Job failures from later global suspension. #327 Codex P2 corrected/re-reviewed and merged.
- 2026-10-30: Host epoch is **revocation of stale local authorization only**, not shared Plan acceptance; fail-closed on unreadable, malformed or busy generation, and keep lock file free of secrets, PID or model data. A Job admitted just before rotation may continue by design.
- Previously reviewed OFF-1A–T private Linux CLI network, SQL, listener, lease, DOCX and mapping decisions remain in complete archives and still apply when those slices are used; stale chronological status does not override current Hosted GitHub.

## Archived History

- `.codex/archive/decisions.md-20261030-101300.md` — re-fetched exact byte-identical pre-compaction active decisions (Git blob SHA `fd37fe3eba51caa455e1269ee0161540bc694e24`, 25,779 characters), including all detailed historical Product, OFF-1 and E2E trust decisions.
- `.codex/archive/decisions.md-20261021-165000.md` — earlier complete review and security decision history.
- 2026-10-30 compaction after >20 dated records follows `AGENTS.md`, preserving current policy and all historical evidence in verified archives.
