# SRAF: GLM Event / Timeline → Evidence time contract (Issue #393)

> Status: PR #395 candidate, hosted synthetic tests only; **not private ES / operator acceptance**.
> This document describes the proposed retrieval behavior, not a production data migration.

## Data sources and authority

GLM `multidim_event_json.Event` stores `event_id, time_iso, time_precision`.
`Event_Timeline` stores `event_ids, time_iso, time_precision`. Structured
`evidence_snippets` currently stores `event_ids, text, source_id, paragraph_id`
but **does not store a trustworthy independent `date_iso`**.
SRAF's `Citation.date_iso` is a derived runtime field.

The retrieval path first correlates each Evidence `event_ids` with its
structured `Event.event_id` and any `Event_Timeline.event_ids`. It includes
both a core Event date and distinct Timeline milestones. Identical periods are
deduplicated (preferring Event provenance). Multiple different candidate dates
within one coherent event ID remain visible and are never collapsed into an
arbitrary first day. Event IDs are **local to each multidim object**, so
structured source Evidence is correlated within its originating block.
Nested inner hits use Elasticsearch's enclosing `_nested.offset` where
available; a multi-block inner hit with no trustworthy origin cannot borrow
another block's repeated ID. Unlocated inner hits whose ID is uniquely
defined within the document may still be resolved conservatively.

- `Event_Timeline=[]` is valid; a dated `Event` suffices for date retrieval.
- An Event-only document and a Timeline-only document can each be found by
  explicit `date_from/date_to` or a 4-digit year inside the query text.
- ES searches the correct outer `multidim_event_json` and inner
  `Event`/`Event_Timeline` nested boundaries. Both sides participate in
  the date filter (OR); evidence is separately checked against linked IDs.
- `year` and `month` are intervals. Never assign an artificial January 1
  or first-of-month day to evidence, statistics, or API presentation. Query
  endpoints are inclusive at the day level, implemented with exclusive
  next-day `lt` bounds on indexed timestamps.
- **Legacy missing/empty `time_precision`** can encode `YYYY`, `YYYY-MM`,
  day or ISO timestamp with an explicit offset. ES date normalization hides
  that source precision. Candidate retrieval must conservatively cover the
  enclosing calendar years plus a UTC boundary day on either side, then
  block-local Evidence time intervals enforce exact query semantics. This
  broader legacy candidate scan requires separate real-index performance
  acceptance; it is not a reason to treat a year/month as an exact day.
- Explicitly unknown/invalid precision is not promoted to a valid time.
- Article publication date remains separately available as `article_date_iso`
  and is **not** an event-date fallback in a structured event document.
- Historical documents **without** Event/Timeline structure keep their
  legacy article-date fallback for compatibility. This exception is not proof
  of a known event date.

## Output contract

For an unambiguous linked **day** event: `evidence_snippets[].date_iso`
contains that event day, even when the article was published later.

For a **month/year** or **multiple distinct days** linked to the same snippet:
`date_iso` is empty, rather than claiming one exact day. Structured evidence
provides extra *optional* keys:

- `event_time_candidates`: all linked candidate intervals, each with
  `time_iso`, `time_precision`, `date_start`, `date_end`, `source`.
- `matched_event_time_candidates`: the intervals that match the request's
  explicit date bounds or natural-language years, if any. This second list
  prevents downstream aggregates from counting a different Timeline milestone
  that was not in the requested period.

Old keys (`uuid`, `text`, `event_ids`, `source_id`, `paragraph_id`,
`article_date_iso`) stay available.

## Aggregation safeguards

`AggregateMonthQuarter` now counts linked, query-matched day precision
events, not their article publication date. Different genuine days for the
same document can each count once; repeated snippets for the same UUID/day
are still deduplicated. A month/year-only candidate is **not** counted as an
exact day. It remains available as a range for future precision-specific
aggregates; month/year-only periods are not silently mixed into existing
document-day monthly counts. Unstructured legacy evidence prefers a valid
`date_iso` over the article date.

Document hits with no date-matching Evidence are not forwarded as
date-qualified reports. A document-level Event hit alone is not proof that a
citation belongs to the same event.

## Verification and residual limits

Offline Python3.10/3.11 contract and legacy regression:
`tests/test_sraf_structured_evidence_time.py`,
`tests/test_nested_event_mapping.py`,
`tests/test_multidim_shape_normalization.py` and
`tests/test_query_terms_contract.py`, gated by
`.github/workflows/sraf-evidence-time-contract.yml`.

**Not proven by hosted tests:** private `news_test` Mapping, ES nested
query execution on actual indexed timestamps and time zones, real record
shape, long-running retrieval performance, Event links absent in legacy
documents, owner workstation/live API and end-to-end DOCX/report correctness.
No Mapping migration or ES write is included. Real ES checks must first be
read-only and separately authorized; unresolved cases remain tracked in
[Issue #393](https://github.com/hun186/poc-agent/issues/393).

The query-layer OR is intentionally a **document candidate filter**, not
proof that a keyword and date belong to one Event. The Evidence link/date
stage is the additional guard. For unclear evidence without reliable
`event_ids`, preserve uncertainty rather than inventing a linked event.

## Report LLM and final citations

The compressed report Evidence `d` is a date **only when precise**. With one
month/year interval it may be the abbreviated `YYYY-MM` or `YYYY`, always
accompanied by `tp` precision and query-matched `times` intervals. Multiple
intervals provide `tp=multiple` and `times`; unresolved evidence provides
`tp=unknown`, and neither case is substituted by article publication date.
The report field selector must retain `tp`/`times` for structured Evidence.
Final citation `date_iso` remains blank for month/year/multiple/unknown,
while `date_precision` and candidate time intervals preserve provenance.
Known `hour/minute/second` input precision retains its original `time_iso`
inside candidate metadata, with its local event day projected for daily
search/aggregation. The event's explicit offset is preserved, not inferred.

## 2026-11-10 P2: refill date-qualified ES candidates after Evidence filtering

Legacy missing/empty `time_precision` requires a widened ES date candidate
window, so the first `size` ES hits can contain only out-of-range records.
The canonical search tool now applies Evidence validation, then fetches further
ES candidates using bounded `from` pagination of the **same body and score
order**, re-evaluating the accumulated hits under the existing global
strict/relaxed matching policy. This applies to explicit `date_from/date_to`
and four-digit query-year conditions. Undated searches keep their original
single-request search and normal fallback.

`query_meta.date_candidate_refill` exposes `candidates_scanned`,
`pages_fetched`, `candidate_scan_limit`, `result_count`,
`search_exhausted` and `incomplete_due_to_scan_limit`. Reaching the
safe candidate budget before the requested number of valid hits sets
`query_meta.result_incomplete=true` and
`note=date_candidate_scan_limit_reached` — it must **never** be presented
as a proven exhaustive zero-result query.

Candidate budget: `min(10000, max(256, requested_size * 32))`,
with refill page size at most 1000 and **no `from + size` beyond 10000**.
The bounded scan is not an exhaustive index-wide search; results above the
budget remain unknown and must be marked incomplete, not silently ignored.
Ordinary ES `from` paging across a concurrently refreshed index is not a
point-in-time snapshot, and tie ordering may move between pages. Operator
read-only acceptance should evaluate real index window, retry behavior,
ordering stability, runtime cost and reporting UX before declaring live PASS.

Offline regressions in `tests/test_sraf_date_evidence_refill.py` include
ranked false positives before the valid candidate, early completion, exhausted
result sets, bounded truncation, natural-language query years and unchanged
unfiltered one-shot behavior. GitHub CI includes these tests on Python 3.10
and 3.11. **No production ES data, schema or service has been modified.**
