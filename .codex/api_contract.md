# API Contract — SRAF (active, compacted 2026-11-11)

## Current Summary

- API routes in `sra_api/routers/`, compatibility in `api/`. Existing auth/RBAC and owner isolation remain authoritative for `/healthz`, `/v1/models`, `/v1/chat/completions`, document retrieval, Report Job POST/status/history/Word and Requirement/Product Profile/Import/Schedule/Handoff APIs. No fabricated production responses or silent migration.
- Report `POST /v1/report/jobs` persists owner-scoped queued/running/terminal state with scoped canonical `Idempotency-Key`; `GET /v1/report/jobs` bounded owner history and optional strict status enum; `GET /v1/report/jobs/{id}` real phase/elapsed status, `GET /v1/report/jobs/{id}/word` authorized DOCX. Browser protects token change/download race and does not blindly retry ambiguous POST.
- Requirement immutable Set/Version/Snapshot/Profile/Run and Product v4 Task activation reuse existing owner/CAS/idempotency and permissions. Existing `POST /v1/requirement-task-previews` normalizes bounded file/JSON, never creates or schedules a Task; Product read-only browser uses only authorized existing GETs.
- Superuser-only `GET /v1/operator-e2e/runtime-evidence` and status use bounded process-local plan/generation and sanitized failure categories. OFF-0/1/2 partial checks, preflight or Hosted fixtures are not a signed FULL_LIVE release acceptance.

### Evidence Trace #397 / #401 — internal diagnostic only

- **No new public API endpoint, request parameter, response field or schema change**. `agent/es/evidence_core/builder.py::build_hits_and_evidence(...)` retains exactly its existing (hits, evidence_snippets, synonym_hit_count) tuple. `ESSearchNews.forward`, `run_data_agent`, report LLM and DOCX payloads are unaffected by the feature.
- New **process environment option** `SRAF_EVIDENCE_TRACE=1` enables a fixed-schema `sraf_evidence_retrieval_trace_v1` structured warning-level **log**, one per Evidence builder invocation. All other values/unset disable it. No additional ES/LLM request or state change.
- Log fields: generated `trace_id`, `scope=single_builder_evaluation_not_final_report`, fixed limits, count breakdown and first 64 hit ordinal / 256 citation ordinal plus fixed reason code records; overflow counters. Parser observes source candidate count, inner returned, chosen source and cap; Evidence stages record accepted and `date_unmatched|date_unknown|date_before|date_after|year_unmatched|empty_text|no_uuid|topic_rejected`. No raw query/text, source identifiers, ES IDs, article dates, `event_ids`, prompts, host paths or credentials.
- This does **not** guarantee a unique per-report trace ID: bounded date-refill may run multiple builder evaluations, each separately logged. No report-level post-dedup, LLM chosen count or token budget telemetry is claimed. Existing application debug prints are outside the new safe trace and may need independent hardening.
- New `build_evidence_snippet(..., rejection_reason=None)` private optional collector provides fixed reason codes. Unset keeps the old behavior and date fail-closed rules.
- Real index/inner hit samples, production authorization, no-network Linux deployment, full report/DOCX and p95 performance remain NOT TESTED by Hosted.

### Other operator / Editor contracts

- #395 date query/report incompleteness warnings already merged; source local Event/Timeline intervals retain precision. #400 Editor optional `search_mode` candidate is **not merged**, real keyword substring/large-index performance unknown and separate from Report/ESSearchNews.
- Operator-only #396 SAN-WARN is **not merged** and must never be treated as production ES server identity. Root 1_ Linux L0/L1 is partial; L2/L3 independently authorized. Linux updates use Windows-to-Linux one-way 7z overlay, no Git checkout.

## Recent Changes

- 2026-11-11 #401 opt-in Evidence builder diagnostic **candidate, not deployed**. Exact-head Hosted CI/Codex Review and live acceptance separate.
- 2026-11-11 #395 temporal integration merged; #400 Editor and #396 SAN diagnostic still open.

## #402 internal report Evidence diagnostic only (candidate, NOT MERGED)

- No new HTTP endpoint/query argument/response key. Existing `ask_with_report`, Report Job status/download, report model request and DOCX schema remain unchanged. Optional `SRAF_EVIDENCE_TRACE=1` logs one `sraf_report_evidence_counts_v1` count-only record before actual report LLM call (or skipped-incomplete marker if date scan incomplete and Evidence empty); no new SQL/ES/LLM request.
- Log numeric counters: `incoming,strong,weak,picked,compressed,llm_input,max_for_llm,prompt_chars,truncated_notes,truncated_titles,strong_or_weak_unselected,removed_during_compression,removed_after_field_selection`; boolean `report_llm_skipped_incomplete_search`, generated random `trace_id`. All counts are stage deltas, not per-item reason codes, and `prompt_chars` is not token count. No raw query/source IDs/note/title/date/prompt/credentials in new logger. #401 retrieval log is separate and cannot be correlated by trace ID.
- Eliminates preexisting unconditional report stdout per-Evidence `id/d/title/note_preview` loop; other legacy logs and prompt-bearing in-memory `trace` are unaffected. No live LLM/DOCX acceptance or release claim. 

## Archived History

Complete prior API contract archived verbatim at `.codex/archive/api_contract.md-20261111-213000.md`, independently re-fetched with identical Git blob SHA `3ca0b353bac76615fa2aaa336b7c5d2e0ab3c313`. Prior archives retained; old candidate status not current Gate proof.
