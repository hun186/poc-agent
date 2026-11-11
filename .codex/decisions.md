# Architecture and Engineering Decisions — SRAF (active, compacted 2026-11-11)

## Current Summary

### Authoritative runtime and data
- Reuse real FastAPI `sra_api/` and `api/` compatibility, Agent/LLM, Elasticsearch, SQL Server immutable Requirement Set/Version/Snapshot/Profile/Import Run, Schedule/Handoff lease workers, and existing SQLite Report Job/DOCX/RBAC/audit. No replacement queue, fake success, unreviewed SQL state or owner bypass.
- Product v4 Task activation/CAS/idempotency/Service Key scope, Report Job owner-scoped status/download, browser bounded history/unknown-response retry and active-auth fencing remain authoritative. SQL transactions cannot atomically coordinate HTTP/ES/file system effects.
- Source/release manifest SHA identities need independent trust, private nofollow output dirs and actual runtime-module checks. OFF-0/1/2/3 `PASS_PARTIAL` is not FULL_LIVE, signed complete Wheelhouse/native ODBC, physical airgap install/rollback or OFF-5 restore.
- Strict OFF-1S socket identity before bearer and valid CA+IP SAN before trusted ES auth. Operator-only CA-WARN exception (PR #396) remains security-sensitive and is never production TLS acceptance. L2/L3 model/SQL/ES/Requirement/DOCX all separately opt-in; cooperative timing is not SDK cancellation.
- Linux deployment is Windows Robocopy/7z **one-way incremental overlay**, no Linux Git; obsolete files may persist and require intentional operator handling.

### Temporal retrieval and Evidence diagnostics
- #395 is the canonical Event/Timeline source-block-local event ID/precision matching plus bounded ES candidate refill and report incompleteness warnings. #394 closed without merge. No implicit article/publication date or unrelated event substitutes for missing Evidence time.
- #397 P1-a first stage uses **opt-in, read-only, bounded** `SRAF_EVIDENCE_TRACE=1` in `agent/es/evidence_core`, not a global persistent tracing service. It records only per-evaluation random ID, numeric hit/citation ordinals, fixed reason codes and limited aggregate counters. No query, UUID, index/ES ID, text, dates, credentials or host paths in new trace.
- Keep existing Evidence query/filter/public output exactly unchanged. Strict/relaxed/fallback counts represent distinct attempts (may rescan citations) and ES date-refill builder invocations must never be added as if global unique results. No extra LLM or candidate recovery triggered by observability; retain date fail-closed behavior.
- #397 P1-b/c/d must be separate, bounded, deterministic and date-safe: candidate retention, low-volume refill, source/time/topic diversity and hard LLM input budget. Do not bypass ES pagination or silently run unbounded leading wildcard, and keep final report completeness warnings authoritative.
- #400 Editor mapping-aware substring search is a separate API/query path from SRAF report search. Real index latency and mapping coverage unknown; no live ES mapping changes.

## Recent Changes

- 2026-11-11 #395 merged authoritative Event/Timeline logic; real private ES/report validation outstanding.
- 2026-11-11 #400 Editor search and #396 special TLS warning remain OPEN, each with distinct operational/security gate.
- 2026-11-11 #401 first `SRAF_EVIDENCE_TRACE` candidate adds retrieval diagnostics without filtering change, Code Review/Hosted/live observation gated.

## Archived History

Full previous decision record preserved verbatim at `.codex/archive/decisions.md-20261111-204500.md` (independently verified identical Git blob SHA `723b3602d143d5df5d15f773d23e43dbdebb6db2`). All earlier archives remain; historical review states are not current acceptance evidence.
