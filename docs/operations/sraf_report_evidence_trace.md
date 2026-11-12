# SRAF report Evidence counts — #397 P1-a follow-up

This is an independent, non-mutating count diagnostic at the actual
report-LLM input boundary. The default report behavior is unchanged.

## Current feature

Set `SRAF_EVIDENCE_TRACE=1` for operator-controlled diagnosis. The default
is disabled; every other value is disabled. The report path emits a fixed
`SRAF_REPORT_EVIDENCE_TRACE={...}` warning-level JSON record immediately
**before invoking** the report LLM, never claiming its response succeeded.
When a date-scoped search is incomplete and yields no Evidence, the existing
fail-closed branch emits a zero-count `report_llm_skipped_incomplete_search`
record and does **not** call the report model.

Counts are measured from the existing in-memory lists at actual stages:
- `incoming`: Data Agent supplied Evidence
- `strong`, `weak`, `picked`: original strong-first and 120-snippet
  (environment-configurable) cap
- `compressed`: actual `compress_evidence` output count, after text/time
  deduplication and equal-spaced sampling
- `llm_input`: actual `pack_ev_for_llm` result list count, immediately
  before `json.dumps` prompt submission
- `prompt_chars`: serialized prompt character count **not tokens**,
  `truncated_notes` and `truncated_titles`: existing note/title caps.

`removed_during_compression` is a stage delta, **not** an exact per-snippet
dedup reason: it may reflect missing text/IDs, temporal dedup or sampling.
`removed_after_field_selection` counts list entries only, not removed
fields. A field-selector may itself call an LLM in existing opt-in modes; the
trace does not add or force any such calls.

The logger accepts fixed count integers/booleans only. It never writes
the question, prompt, note, UUID, article title/date, host path, credential
or raw Data Agent payload. Each report call gets its own random log ID;
**this does not correlate** with #401's retrieval-stage trace IDs. No
added API response keys or persistent traces.

## Privacy change

Previously `agent/report_agent.py` printed every LLM Evidence's
`ref_no`, `id`, `d`, `title`, raw note preview and selected keys to
ordinary stdout by default. This PR **removes** that unconditional content
printing, not by hiding logs behind another flag. The new count-only
diagnostic is safe-by-schema, opt-in. Other older application diagnostics,
in particular ES search logs and the internal `trace["llm"]["report"]`
prompt retention, are **outside this PR** and may require separate
review before logs are shared.

## Verification and non-goals

Hosted Python 3.10/3.11 tests use synthetic Data Agent and LLM doubles
to exercise the original report path and assert identical report success
and no extra model calls, 120+ strong/weak selection, duplicate compression,
note truncation, incomplete-date zero-report fail-closed and stdout secrecy.
No real ES, SQL Server, model, DOCX or production Linux was accessed.

This does not implement report token-budget enforcement, per-snippet
post-dedup removal reasons, cross-stage IDs, additional ES lookups or
automatic candidate recovery. Those remain #397 P1-b/c/d and a future
privacy-safe cross-stage trace step. No Git commands are required on the
one-way Windows→Linux incremental deployment host.
