# SRAF #397 P1-c — bounded _source refill for omitted ES inner_hits

## Baseline and expected effect

ES may return only three matching nested `evi` inner hits even when a single
document contains five or more `multidim_event_json.evidence_snippets`.
`parse_es_hits` intentionally prioritizes `inner_hits`, and historically
does not supplement from `_source` when any inner-hit citation exists.

This candidate allows recovering 1–2 extra source citations from an already
strongly anchored document; example: 5 structured snippets, 3 returned as
inner_hits, only 1 strict Evidence survives → **up to 3** after source refill.
Actual results depend on topic/date links and candidate ordering; this does
not assert that a specific user's private article has this exact cause.

## Dual opt-in, no new I/O

- `SRAF_EVIDENCE_RESCUE=1` **AND** `SRAF_EVIDENCE_SOURCE_REFILL=1`
  are both required. If either is off, existing #404 behavior remains
  unchanged. Both default OFF.
- Source-only reparse receives a **bounded allowlisted projection** of the
  existing ES response `_source`: uuid, structured Event, Timeline, date,
  title, source evidence `text/event_ids/source_id/paragraph_id`; never sends
  new ES/LLM requests or emits candidate text in logs.
- Refills only from the exact source-hit ordinal already validated by
  **non-weak, strict Evidence text match**. Same application `uuid` across
  ES indices is not an identity.
- Every source citation must carry **complete, block-local Event/Timeline
  time links**; the original `build_evidence_snippet` applies the original
  requested range and years again. Missing/invalid links, other dates,
  unstructured documents, metadata-only matches and duplicate existing
  citations do **not** qualify.
- Newly found strict source citations outrank weak candidates. Existing #404
  parsed weak rescue runs next; newly found weak source candidates fill
  remaining slots only. Strong original Evidence remains unchanged and
  first in output; selected source citations appear in the corresponding
  hit's `citations`, not only in Evidence output.
- Limit: source-reparse at most 3 strict-anchored ES documents, 8 blocks/doc,
  48 source citations inspected/doc, 12 projected citations/doc, 2,048 chars
  per candidate, 32,768 source-text chars/doc, 160,000 chars max for JSON
  `multidim_event_json`, 12 held candidates globally, at most **2 extra**
  selected with combined 3-Evidence target. Oversized fields are skipped or
  rejected. Existing ES date-page cap remains unchanged.

## Verification and residual work

- `tests/test_sraf_source_evidence_refill.py` uses synthetic ES responses
  with `inner_hits` and `_source` containing 5+ citations, wrong Event
  dates, repeated IDs across blocks, duplicate UUID across different
  indices, explicit incomplete Event linkage, source JSON encoding, 500+
  source citations, oversized candidate, source-only legacy and both
  feature-flag OFF combinations.
- `.github/workflows/sraf-source-evidence-refill.yml` runs Python 3.10/3.11
  with existing source/structured-date, #404 rescue and #403 synonym tests.
- This is a **conservative first P1-c slice**, not full adaptive retrieval:
  does not expand `inner_hits.size` in ES, issue additional ES requests,
  scan unlimited source citations, rescue absent strongly anchored documents,
  cover unconstrained raw-content legacy text, or fix Report Job token/top-k
  selection. Extra source citations skipped by caps remain intentionally
  uncounted; no promise of exhaustive results.
- Real private `news_test` Mapping/Analyzer, 2023-08-24 5→1 Guterres case,
  actual recall/precision, p50/p95, token spend and full Report Job/DOCX
  **NOT TESTED**. Separate private read-only acceptance required.
