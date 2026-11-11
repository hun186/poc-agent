# API Contract — SRAF (active, compacted 2026-11-11)

## Current Summary

- API routes in `sra_api/routers/`, compatibility in `api/`. Existing auth/RBAC and owner isolation remain authoritative for `/healthz`, `/v1/models`, `/v1/chat/completions`, document retrieval, Report Job POST/status/history/Word and Requirement/Product Profile/Import/Schedule/Handoff APIs. No fabricated production responses or silent migration.
- Report `POST /v1/report/jobs` persists owner-scoped queued/running/terminal state with scoped canonical `Idempotency-Key`; `GET /v1/report/jobs` bounded owner history and optional strict status enum; `GET /v1/report/jobs/{id}` real phase/elapsed status, `GET /v1/report/jobs/{id}/word` authorized DOCX. Browser protects token change/download race and does not blindly retry ambiguous POST.
- Requirement immutable Set/Version/Snapshot/Profile/Run and Product v4 Task activation reuse existing owner/CAS/idempotency and permissions. Existing `POST /v1/requirement-task-previews` normalizes bounded file/JSON, never creates or schedules a Task; Product read-only browser uses only authorized existing GETs.
- Superuser-only `GET /v1/operator-e2e/runtime-evidence` and status use bounded process-local plan/generation and sanitized failure categories. OFF-0/1/2 partial checks, preflight or Hosted fixtures are not a signed FULL_LIVE release acceptance.

### Evidence Trace #397 / #401 — internal diagnostic only

- **No new public API endpoint, request parameter, response field or schema change**. `agent/es/evidence_core/builder.py::build_hits_and_evidence(...)` retains exactly its existing (hits, evidence_snippets, synonym_hit_count) tuple. `ESSearchNews.forward`, `run_data_agent`, report LLM and DOCX payloads are unaffected by the feature.
- New **process environment option** `SRAF_EVIDENCE_TRACE=1` enables a fixed-schema `sraf_evidence_retrieval_trace_v1` structured warning-level **log**, one per Evidence builder invocation. All other values/unset disable it. No additional ES/LLM request or state change.
- Log fields: generated `trace_id`, `scope=single_builder_evaluation_not_final_report`, fixed limits, count breakdown and first 64 hit ordinal / 256 citation ordinal plus fixed reason code records; overflow counters. Parser observes source candidate count, inner returned, chosen source and cap; `parser.source_uninspected_after_cap` counts raw source rows never examined when the per-document parser source cap stops early (validity unknown, separate from post-parse `parser.citations_capped`); Evidence stages record accepted and `date_unmatched|date_unknown|date_before|date_after|year_unmatched|empty_text|no_uuid|topic_rejected`. No raw query/text, source identifiers, ES IDs, article dates, `event_ids`, prompts, host paths or credentials.
- This does **not** guarantee a unique per-report trace ID: bounded date-refill may run multiple builder evaluations, each separately logged. No report-level post-dedup, LLM chosen count or token budget telemetry is claimed. Existing application debug prints are outside the new safe trace and may need independent hardening.
- New `build_evidence_snippet(..., rejection_reason=None)` private optional collector provides fixed reason codes. Unset keeps the old behavior and date fail-closed rules.
- Real index/inner hit samples, production authorization, no-network Linux deployment, full report/DOCX and p95 performance remain NOT TESTED by Hosted.

### Other operator / Editor contracts

- #395 date query/report incompleteness warnings already merged; source local Event/Timeline intervals retain precision. #400 Editor optional `search_mode` candidate is **not merged**, real keyword substring/large-index performance unknown and separate from Report/ESSearchNews.
- Operator-only #396 SAN-WARN is **not merged** and must never be treated as production ES server identity. Root 1_ Linux L0/L1 is partial; L2/L3 independently authorized. Linux updates use Windows-to-Linux one-way 7z overlay, no Git checkout.

## Recent Changes

- 2026-11-11 #401 opt-in Evidence builder diagnostic **candidate, not deployed**. Exact-head Hosted CI/Codex Review and live acceptance separate.
- 2026-11-11 #395 temporal integration merged; #400 Editor and #396 SAN diagnostic still open.

## Still-valid API contracts retained after 2026-11-11 compaction

- **Excel→SQL source statistics:** Authenticated `GET /v1/excel-to-sql/source-stats` is restricted to authorized data editors and configured destination tables. Existing filters, grouped stats and import-time series remain. Optional `include_numeric_summaries: bool=false` does **not** execute an extra numeric aggregate when false. When true, at most one bounded read-only aggregate query covers up to **six** eligible numeric destination columns (excluding system/hash columns). Response includes `numeric_summaries` entries `{column,count,min,max,average,sum,approximate}`, `numeric_summaries_enabled`, `numeric_summary_available_columns` and `numeric_summary_limit=6`. `count` counts non-null values; min/max preserve SQL values; FLOAT average/sum are **approximate**, not precise accounting totals. No unrestricted SQL, extra default scan or automatic data write.
- **Report Jobs:** `POST /v1/report/jobs` supports owner-scoped semantic `Idempotency-Key`: identical replay returns existing Job (202), changed request under the same key yields 409; ambiguous browser retries reuse the identical key/body only on explicit user action. Authenticated `GET /v1/report/jobs?limit=20&offset=0` lists *only* the current owner, `limit` 1–100 and `offset` 0–10000, no total count and no prompts/metadata/secrets. Optional `status` is strictly one of `queued|running|completed|failed|interrupted` (invalid → HTTP 422) and filters before pagination; even privileged admin cannot enumerate another owner's list. Individual status exposes observed durable phase/progress, not model/GPU time guarantee; `/word` reauthorizes DOCX.
- **Requirement/Product browser:** `GET /requirement-product` displays existing authorized `GET /v1/requirement-tasks`, `GET /v1/requirement-runs`, task/run details, task runs and run items using bounded (normally 20/offset) pagination and nonpersistent bearer, not SQL or Job write authority. `GET /v1/requirement-import-profiles` exposes enabled/active-version choices; approval is enforced by backend. `POST /v1/requirement-task-previews` requires existing `db_operator`, bounded CSV/JSON/XLSX or a JSON-array input, approved Profile Version, and only normalizes/validates; it never persists/activates a Task, schedules jobs or mutates SQL.
- **Operator contracts:** Superuser-only `GET /v1/operator-e2e/runtime-evidence?verification=release|functional`, `/status`, and scoped batch-item artifact routes report local Plan/provenance and authorized constrained outputs, not cross-host permission or independent FULL_LIVE proof. Protected browser/download capabilities and owner/RBAC boundaries remain unchanged. Historical exact request fields and versions are retained verbatim in the linked archive; these concise live guarantees must stay in the active contract.

## Archived History

Complete prior API contract archived verbatim at `.codex/archive/api_contract.md-20261111-204500.md`, independently re-fetched with identical Git blob SHA `3ca0b353bac76615fa2aaa336b7c5d2e0ab3c313`. Prior archives retained; old candidate status not current Gate proof.
