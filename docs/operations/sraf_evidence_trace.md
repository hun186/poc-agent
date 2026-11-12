# SRAF Evidence Trace — P1-a retrieval-stage diagnostic

Issue: #397. **Candidate only: no live Elasticsearch/LLM/DOCX acceptance**.

## Scope and activation

The existing Evidence retrieval/parser now has a **disabled-by-default**,
read-only stage diagnostic. Set `SRAF_EVIDENCE_TRACE=1` only for an
operator-controlled investigation. All other or unset values disable it.
The feature does **not** change the ES query, Evidence filtering, selected
snippets, query result schema, report API, number of LLM calls or DOCX.

One `SRAF_EVIDENCE_TRACE={...}` structured **warning-level** log record is
emitted for *each builder invocation*. A query that uses bounded ES date
candidate refill may invoke the builder more than once. Each invocation
has a random trace ID and must be interpreted **independently**, not added
together as a global total or treated as an end-to-end request trace.

The record reports:
- Per ES hit *ordinal* (not index/ES ID/UUID): source evidence candidates,
  received `evi` inner hits, parsed citations, selected after parser cap,
  and `inner|source|fallback|none` source selection. `parser.source_uninspected_after_cap` records raw source items never examined after the source parser reaches its per-document cap (for example 25 source rows → 20 parsed → 5 uninspected). This is **not** the count of proven valid Evidence excluded: those rows were never date/format/topic validated. `parser.citations_capped` is separate, for already parsed citations that were then trimmed.
- Per parsed citation (ordinal within that hit), strict/relaxed/zero-term/
  any-term fallback stage outcome. Date rejection reason codes:
  `empty_text`, `date_unmatched`, `date_unknown`, `date_before`,
  `date_after`, `year_unmatched`, `no_uuid`. Topic rejection:
  `topic_rejected`. Accepted: `accepted`, `fallback_selected`.
- Final builder selected document/evidence counts and whether any relaxed
  pass was used. **Strict and later pass counters are distinct attempts**:
  the same citation may be evaluated more than once if strict count is zero.
- Fixed limits: first 64 hit records and first 256 citation records, with
  accurate aggregate counters and overflow counts for all remaining rows.

No raw text, query, event ID, document identifier, title, file path, timestamps,
embedding, model prompt or credentials are added to the new trace.
Numeric ordinals are only meaningful **within a builder evaluation**; they
cannot prove that two requests refer to the same ES document. Treat the
existing application logs as potentially more sensitive, independent of the
new diagnostic. Protect, retain and share logs according to private-host policy.

## What it establishes and does not establish

This is **retrieval-stage evidence**, not the final report's selected Evidence
list. It can show whether five `_source` snippets were observed, whether
only three `inner_hits` were returned and whether four available citations
were rejected because of date/topic rules. It **cannot** recover citations
never sent by Elasticsearch, explain ranking of omitted ES documents, or
guarantee a root cause if the source snippet was never available to parser.

No token budget, extra candidate refill, Evidence reranking, deduplication,
report truncation, LLM field selection, true prompt token counting or
final DOCX provenance is implemented here; #397 P1-b/c/d and the downstream
P1-a stages remain TODO. In particular, date-invalid Evidence remains
excluded, and no article date is substituted for an unrelated Event date.

## Validation

Hosted Python 3.10/3.11 offline regressions (no services) compare exact
returned hits/Evidence with tracing enabled versus disabled, inspect reason
codes and privacy, large synthetic trace caps, 5→1 topic filtering,
Event date invalidity and inner-hit/parser caps. Existing event-time and
date-refill regression suites must still pass. These are synthetic tests:
the operator's actual 2023-08-24 Guterres case and private `news_test`
Mapping/inner_hits performance remain **NOT TESTED**.

No Git commands are required on the user's one-way-incremental Linux
deployment host. This code must not be overlaid onto the running service
from an unmerged PR as routine acceptance.


## Integrated #404/#405 rescue stages (2026-11-12)

The retrieval trace is now integrated with the current merged Evidence pipeline
instead of reverting to the old pre-rescue builder. With both trace and rescue
flags enabled, it also includes **fixed-name count-only** counters:

- `source_refill.strict_candidates` and `source_refill.weak_candidates`:
  eligible source-only candidates found by the already-bounded, same-ES-hit
  #405 stage. These are NOT all source evidence entries, nor complete reasons
  for why other `_source` entries were excluded.
- `source_refill.strict_selected` and `source_refill.weak_selected`:
  candidates actually selected into Evidence under the shared low-count target.
- `source_refill.unselected_by_target`: *eligible* source candidates not
  selected after the existing bounded refill (never claim date invalidity).
- `bounded_rescue.selected`: weak Evidence actually added from already-parsed
  citations by #404.

Counters are zero/absent when their feature stage is disabled, rather than
fabricating dates, identities or hypothetical candidates. The original
`strict_accepted` counter is **before** #404/#405 additions; final
`output_evidence` is **after** additions. Date and topic reasons for original
strict/relaxed/fallback passes are unchanged. Refilling is still protected by
`SRAF_EVIDENCE_RESCUE=1` and separately by
`SRAF_EVIDENCE_SOURCE_REFILL=1`, both default OFF; the Trace flag is
independent and does not activate either.

These are **per-builder evaluations**, not per-request global totals and not
the final Report Agent/LLM context. A date-refill ES query may evaluate many
builder iterations; do not sum them as unique Evidence. Report-stage count-only
trace remains separate in PR #402, and there is no per-citation cross-stage
correlation key in these safe logs. Sensitive names and source material must
never be added to the trace payload. Private `news_test` and the user's
2023-08-24 example remain unverified.
