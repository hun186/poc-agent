# Backlog

## Current Summary

### OFF-1I PR #305 — immediate review and deployment gates

- Complete mandatory AGENTS.md memory compaction: full original `.codex/memory.md` and `.codex/backlog.md` were archived before overwrite at `.codex/archive/{memory,backlog}.md-20261024-170825.md` and byte-for-byte verified. Keep these archive references in active memory.
- Run and inspect exact-current-HEAD Hosted OFF-1I/legacy E2E pytest and 19 OFF-0 schema contract checks after memory edits. Reply to initial Codex P1 memory-compaction finding, resolve thread after real preservation/condensation evidence and submit a fresh formal review. Correct any new findings, do not Merge without explicit user command.
- OFF-1I Handoff Coordinator lease diagnostic is a **single DB snapshot only**: default-off `--probe-network --probe-sql-read --probe-worker-lease` with a genuine OFF-1G SQL-READ PASS, readonly separate DBA-limited diagnostic SQL principal, numeric private IPv4/ODBC Driver18/strict SAN. Query only server-computed flags from known `sra_schedule.requirement_handoff_coordinator_leases`, never owner/token or job data. Active snapshot does NOT prove local Worker ownership or renewal/progress. No private Linux/SQL Server acceptance yet.
- After approved merge, obtain authorized private Linux evidence and identify any real SQL certificate/DB schema/permission issue without downgrading to an unsafe TLS or privileged account.

### Live acceptance still pending

- Real deployment acceptance remains INCOMPLETE. Verify ES index selector/Mapping against actual protected service; past `mapping_incompatible` and relocated Docker IP SAN mismatch were not cleared by Hosted CI. CA-verified but IP-identity-unknown WARN is not strict TLS identity evidence.
- Run authorized SQL Server schema v4/migrations, rollback/failure injection, fencing/failover, concurrent actors, HA and service privilege checks on controlled environment. OFF-1G fixed SELECT and OFF-1I one lease snapshot do not replace these tests.
- Independently prove Schedule Worker claim/progress (the current schema has no independent scheduler heartbeat), Handoff *local owner* association and repeated heartbeat/lease changes, API Report Job Worker, real Agent/LLM/ES execution, and signed/valid Word artifact SHA256. Do not trigger production schedules or mutate leases as diagnostics.
- Run full Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX E2E and OFF-2 release packaging, OFF-3/4 operator reporting, OFF-5 recovery/true physical airgap validation after separate approvals. No report of FULL_LIVE from partial checks.
- Complete launcher deployment and durable output-root migration gates SD-1–SD-7, with per-host evidence and no speculation.

### Product implementation and security backlog

- Requirement Product follows Design/Plan v1, Phase 1B Import / Phase 1C Schedule/Handoff / Report Job, and existing SRA Editor Auth/RBAC; no parallel execution, queue, identity or report storage.
- Preserve immutable Requirement Version/Snapshot, Product Task provisioning/active/disabled, durable request idempotency with cross-resource canonical hash, superuser-only create/activation, draft CAS/owner fencing, controlled Schedule enablement and accurate request projection. Product P1.0–P1.6 historically merged via #283–286; verify current GitHub state of P1.7, P2.1 PR #288 and later work independently before calling merged/complete.
- P2.2, Product HTTP mutation and service-key scopes, Task Center UI/browser E2E, cross-Task result sharing and privacy/ACL/provenance require separate work and approvals.
- Job Task JT-1 and LangGraph integration remain NOT STARTED absent later exact-source evidence. Other future work: Report Job retention/metrics/cancel-retry-webhook, HA/exactly-once, stronger auth throttling/MFA/CSP/CSRF, audit filtering, import diagnostics and SQL/ES lineage.
- Future Worker loaded-code attestation requires reviewed IPC; sanitized SQL-registry proof must not reveal runtime secrets or introduce unsafe hash overrides.

## Recent Changes

- 2026-10-24: OFF-1H PR #304 merged with canonical fd-bound no-follow Worker identity verification, NUL-argv matching, and legacy E2E regression; its successes are point-in-time process checks only.
- 2026-10-24: OFF-1G PR #303 merged with TLS-verified operator SQL fixed constant SELECT; production SQL permissions unverified.
- 2026-10-24: OFF-1F PR #302 merged after cloud-forwarding P1 remedy; LLM local server verifies `OLLAMA_NO_CLOUD=1` by listener PID, but still no actual private Linux acceptance.
- 2026-10-24: OFF-1I PR #305 initial exact-head #40080725404 Hosted pytest 1,079 + two legacy E2E PASS, OFF-0 19 PASS; formal Codex first round identified memory compaction P1, now being corrected. Current exact HEAD requires new checks.
- 2026-10-24: active memory file compaction preserves all earlier OFF-1B/ES PR #295–301, Product and audit review chronology in byte-identical full archives, so older PR status statements in archived logs should not be mistaken for current Hosted GitHub state.
- 2026-10-21: previous mandatory memory compaction archived all six project records; see links in `.codex/memory.md`.

## Archived History

- `.codex/archive/backlog.md-20261024-170825.md` — verified full 20,489-character pre-compaction backlog containing all historic dated blocks and pending tasks before OFF-1I P1.
- `.codex/archive/memory.md-20261024-170825.md` — corresponding verified full 38,469-character pre-compaction project memory.
- `.codex/archive/backlog.md-20261021-165000.md` — prior full history; older 2026-10-06 and 2026-09-18 archives reachable through its references.
- Consult archives only for relevant history, not for every regular current task.

## Compaction Record

- 2026-10-24: original full files **created in .codex/archive and re-fetched with identical bytes and Git blob SHA** before any active memory rewrite. This active backlog now lists only current unresolved actions and durable design constraints; stale chronological review details remain recoverable. After these documentation commits, require exact-HEAD Hosted CI, formal Codex CLEAN and explicit merge authorization.
