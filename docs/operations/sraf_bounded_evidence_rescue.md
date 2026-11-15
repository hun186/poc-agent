# SRAF #397 P1-b / low-count rescue — bounded, default off

## Problem and scope

Existing builder retains only strict Evidence if **any** strong citation survives.
For 5 parsed candidates → 1 strict citation, the existing zero-result relaxed
path is not invoked. This can omit relevant paragraphs from the same article,
even though that article has already demonstrated an Evidence-text strict hit.

This small opt-in slice rescues up to **two** already-parsed citations per builder
call only when `SRAF_EVIDENCE_RESCUE=1`, strict count is **1 or 2**, and at least
two semantic topic groups exist. No new ES/LLM requests, new API, Mapping,
database write, report model call or change in result shape. Default OFF is
byte-for-byte equivalent to legacy output in the offline regression fixture.

## Eligibility — fail closed

1. **Anchor:** candidate must be from **the exact same ES source-hit ordinal**
   as an accepted strong strict Evidence-text citation. Same `uuid` across
   indices or documents is **not** a valid match.
2. **Time:** call existing canonical `build_evidence_snippet` on every candidate
   with unchanged `date_from/date_to/allowed_years`. If invalid, omit. Never
   borrow article publication date when a structured Event link conflicts.
3. **Topic:** candidate must contain a match in Evidence **text** for at least
   one topic axis. Metadata/title only is rejected. A strong strict match
   remains strict and is not duplicated as a rescue.
4. **Output:** rescue is explicitly `weak_evidence=True`,
   `match_policy="bounded_rescue"`, with `group_hits` and `synonym_hits`.
   Strong strict Evidence always precedes rescued weak Evidence.
5. **Budget:** at most 12 strict-anchored documents, 96 inspected citations,
   8 citations/document, 24 pooled candidates, 2,048 chars/candidate,
   65,536 candidate chars in a call, 2 rescued citations/document, and
   **3** total Evidence target. Oversized text is **skipped**, not truncated.
   Tie-break is deterministic: group count, ES score, source-hit order,
   citation order.

## Verified only with synthetic fixtures

- Off/on comparison for five candidates and one strict survivor: 1 → 3.
- Event/Timeline empty; same source Event link; wrong-day E2 and duplicate
  E1 in a different multidim block cannot borrow date.
- Independent same-UUID documents cannot anchor one another.
- A metadata-only candidate is rejected; no rescue when zero or already ≥3
  strict results; single query axis does not trigger rescue.
- 500 unrelated source hits do not inflate the bounded pool; long citation
  skipped, no raw candidate text logged.

This is **not** P1-c final adaptive refill: it does not scan the untouched
`_source` citations when ES `inner_hits` provides only 3, does not rank by
source diversity/token budget or add cross-document candidates, and cannot
guarantee that Guterres 2023-08-24 real-case 5→1 has this root cause.
`date_refill` still aggregates ES pages and can invoke builder repeatedly;
max total ES/page budgets, dedup and incomplete flag remain unchanged.
Actual `news_test` retrieval/Report Job/token count/p50/p95 need separately
authorized read-only operator verification.

No privileged network or Linux deployment is part of this change.
