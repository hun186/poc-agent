# System Architecture — SRAF (active, compacted 2026-11-11)

## Current Summary

### Runtime and data authority
- FastAPI `app.py`/`sra_api/` with `api/` compatibility, real `agent/` question routing/retrieval/LLM/report/DOCX, `data_ingestion/` source import and SQL Server Requirement Set/Version/Snapshot/Profile/Run authority; separate `requirement_scheduler/` and `sra_schedule/` versioned Schedule/Handoff Worker leases.
- Durable owner-scoped SQLite ReportJobStore tracks Job phases/status/download and uses existing API-lifespan Worker. It is not a new queue or a substitute for SQL immutable authority. Product Tasks reuse existing Profile/Run/Worker pipeline with owner/CAS/idempotency and Service Key scopes.
- Security boundaries: `data_reader`, `data_editor`, `db_operator`, `superuser`, signed action capabilities, scoped bearer, strict local socket identity, nofollow private output, signed reviewed package inputs and ES/SQL TLS identity. No fake production mode, global mutable Job registry or automatic privilege escalation.

### Event/Timeline and Evidence data flow
- Canonical #395 `agent/es/event_time.py` joins local multidim Event and Event_Timeline precision intervals to citations via block-local `event_ids`; `agent/es/query_body.py` builds nested Event/Timeline query, `agent/tools_es/date_refill.py` bounds candidate pages with truthful `result_incomplete`, and `agent/es/evidence_core/{parser,builder,snippet}.py` date-qualifies Evidence before topic selection. Never substitute unrelated article date for structured events.
- Current ES `inner_hits` top 3, parser inner-first preference, source citations cap 20, strict topic matching, relax only when strict Evidence=0, strong-first report max 120 and later `compress_evidence` dedup/packing are **distinct loss stages**. Actual per-stage user case remains unverified.
- #401 new **disabled-by-default** `agent/es/evidence_core/trace.py`: in `SRAF_EVIDENCE_TRACE=1` only, per builder invocation with random trace id/numeric hit ordinals/citation ordinals and fixed reason-code counters. Parser observes source candidate count vs inner hits/chosen mode/cap; date and topic strict/relaxed/fallback stages record accepted/rejected. Fixed first 64 document and 256 citation records, accurate aggregate and overflow; no source/raw query/UUID/ES ID/event ID/article date/prompts are written by this logger.
- Tracing neither changes `build_hits_and_evidence` public response nor the result shape of `ESSearchNews`, Report Job or report agent. It does not span ES refills or downstream LLM and cannot prove final report selection. New synthetic `tests/test_sraf_evidence_trace.py` and Python3.10/3.11 `.github/workflows/sraf-evidence-trace.yml` are offline, not real ES.
- Report `agent/report_agent.py` still does strong/weak selection, `compress_evidence` and `pack_ev_for_llm` before actual `call_llm`. Existing debug prints can include raw content independently of #401 safe trace; future P1-a report stage and privacy hardening required.

### Operator and release boundaries
- `1_完整診斷驗收_SRAF.sh` and `scripts/diagnostics/` L0/L1 are passive or bounded TCP /healthz and partial; explicit L2 credentialed SQL/ES/Ollama and L3 Report Job or full existing Requirement Harness require separate authorization and OFF-1S identity. Operator-only event-date sidecar ZIP is not a running-service deployment.
- `shared/runtime_provenance.py`, `REQUIREMENT_E2E_PROVENANCE.json`, `tools/deployment_manifest_policy.json` and OFF-2 partial Wheel/runtime hashes do not establish complete native loader ABI, signed dependency closure, physical airgap or restore. Host uses Windows Robocopy/7z **one-way** overlay, without Linux Git checkout. Old files may persist.

## Recent Changes and Open Gates

- 2026-11-11 #395 temporal retrieval merged; private live ES/date/report acceptance outstanding.
- 2026-11-11 #400 Editor substring/nested search pending private index performance; #396 SAN warning pending security review.
- 2026-11-11 #401 Evidence Trace first slice pending exact-head CI/Codex Review, real source/inner sample and report-level extension. No live ES, LLM, SQL, DOCX or service restart performed here.

## #402 report-side diagnostic (candidate; independent branch)

- In `agent/report_agent.py`, the existing Data Agent Evidence flows through strong/weak priority and `REPORT_MAX_EVIDENCE_SNIPS`, `agent.utils.citations.compress_evidence` (dedup/sampling), optional character truncation, `agent.utils.evidence_pack.pack_ev_for_llm` (field choice), then `json.dumps(compressed_for_llm)` immediately before the actual report `call_llm`. New `agent/utils/report_evidence_trace.py` observes numeric counts at that boundary when `SRAF_EVIDENCE_TRACE=1`; normal output unchanged and no state persisted. The original unconditional Evidence note-preview/UUID/title/date stdout loop is removed. Incomplete date with zero Evidence still aborts without invoking LLM and emits optional skipped-count log.
- There is no request-context correlation to #401 per-builder stage traces, no per-snippet reasons after compression and no hard prompt token budget. PR #401's retrieval instrumentation is **not merged into this branch**; #402 is independent on main. Multiple open PRs update project memory and need conflict reconciliation.

## Archived History

Full previous architecture was archived verbatim at `.codex/archive/architecture.md-20261111-213000.md` and re-fetched to identical blob SHA `f4637f782b33c39c410eff822fd1bc6a44d6c80b`. Earlier archives remain; old pending PR states are historical.
