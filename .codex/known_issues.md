# Known Issues — SRAF (active, compacted 2026-11-11)

## Current Summary

- **Evidence and acceptance:** Hosted CI, 19 OFF-0 schema checks and L0/L1 `PASS_PARTIAL` are not private FULL_LIVE Requirement/Schedule/Handoff → Agent/LLM/ES → Report Job/DOCX, signed bundle, isolated install or OFF-5 restore. No routine credentialed ES/SQL writes, service restart or model invocations without explicit operator scope.
- **Strict trust:** OFF-1S exclusive socket identity required before Bearer. SQL Server native ODBC18 load, TLS/authorization, real Worker leases and artifacts still require proof; CA-chain trust without matching ES IP SAN cannot establish intended server identity. Special operator SAN-WARN PR #396 remains open pending separate security review/high-risk decision, never release-grade TLS acceptance.
- **Date correctness:** #395 merged but real private `news_test` Mapping, source nested offsets, Event/Timeline precision, timezone handling, date-scoped paging and final LLM/DOCX interpretation unverified. Missing/ambiguous links must never borrow another event/article publication date. Bounded refill is not a PIT snapshot and can expose partial results.
- **One-way deployment:** Windows Robocopy/7z incremental overlays onto Linux; no Linux Git checkout. GitHub deletion of root old `0_` diagnostic may not delete deployed copy. Independently checked release manifests, full transitive Wheelhouse native dependencies, airgap installation/recovery and restore remain NOT TESTED.
- **Report/routing:** Existing Report Job SQLite owner-scoped phases, cancellation/timeout and browser retry/Word auth must not be inferred full-featured from hosted tests. Query refiner and old production debug prints can contain original query/Evidence; new #401 logs do not make the **preexisting** global logs privacy-safe.

## Current P0/P1 Open Issues

- **#397 P1 Evidence Trace / adaptive evidence:** Current nested ES `inner_hits.size=3` can truncate before parser sees source candidates; parser inner-first policy skips additional source snippets, `citations_per_doc=20` limits fallback source; topic-match relaxes only when *zero* strict Evidence; report strong-first 120 snippet default plus later dedup/field selection may remove important coverage. Cause of real 2023-08-24 Guterres five→one report NOT CONFIRMED.
- **#401 candidate P1-a first retrieval-only slice:** off-by-default `SRAF_EVIDENCE_TRACE=1` records per-builder parser source-vs-inner count, date/topic strict/relaxed/fallback fixed reason codes, and capped 64 hit / 256 citation entries, never source text/identifiers/dates/query/prompts. Its random trace IDs and hit ordinals are meaningful **only within one builder invocation**, not across ES refills or the final report. No candidate conservation, LLM prompt token count, report dedup reason, or final LLM evidence count yet. Real private ES sample, performance, Hosted exact HEAD and formal Code Review are NOT TESTED until separately evidenced.
- **#398 / PR #400:** Editor new bounded `*literal*` keyword search (auto for underscore) and nested scopes passed synthetic CI/Formal Review at earlier exact HEAD; real large-index `search.allow_expensive_queries`, latency p50/p95 and matching Mapping field coverage remain unknown. No live Mapping write/reindex authorized.
- **#393 P0:** Event/Timeline proof and incomplete-date report UX remain for private operator after code integration.
- **#290:** signed dependency closure, trusted runtime model/ODBC/native SQL and private FULL_LIVE/airgap acceptance remain outside Hosted.

## Required Follow-up Gates

1. Confirm current PR HEAD and full Hosted CI + formal Codex Review/threads; check effects on no-trace public output, privacy/log truncation and Python 3.10.
2. Enable new diagnostic only on trusted operator host/process if authorized; **do not** upload raw application logs from existing debug paths. Review safe fixed-schema log and actual five-to-one Evidence chain in redacted form, distinguishing ES source candidates from returned inner hits and parser vs topic/date rejection.
3. Add later, separately reviewed #397 P1-b/c/d bounded date-safe refill, deterministic diversity coverage and report/LLM token trace; no increase in LLM calls by default.
4. Verify private native SQL/ES identities, Worker/Handoff/DOCX/rollback with independently trusted deployment/source evidence; no automatic fail-open.

## Archived History

Full prior active file archived verbatim at `.codex/archive/known_issues.md-20261111-204500.md` and independently re-read to identical blob SHA `3a5dec9e56b9999c45c5873d7f593b630f4a6358`. Earlier archives preserved; previous speculative PR statuses are historical only.
