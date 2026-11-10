# SRAF #393 — concurrent PR #394 / #395 integration record
Date: 2026-11-10. **Candidate only; #394 CLOSED without merge, #395 OPEN and ready for formal review. Neither PR has merged to main.**

## Why integration was required

[PR #394](https://github.com/hun186/poc-agent/pull/394) and
[PR #395](https://github.com/hun186/poc-agent/pull/395) forked from the same
main commit `555452ed5dcf88f014d0980e55301ee31387e73f`.
They edit nine identical implementation paths across `agent/es/evidence_core`,
`agent/es/query_body.py`, temporal statistics, and final citations.

This is not a trivial git-conflict resolution: #394 introduces
`agent/es/temporal.py` and `agent/es/date_filters.py` with the
`date_window/date_unresolved` contract, while #395 introduces
`agent/es/event_time.py` and structured
`event_time_candidates/matched_event_time_candidates` with corresponding
`tp/times` report compaction.

**Single implementation decision:** integrate on #395 rather than import both
different helpers, nested queries and two competing citation schemas. The #394 branch and code remain intact for audit after its PR was CLOSED
without merge. It must not be merged independently. This avoids duplicate temporal sources of truth.

## Reconciliation (not a blanket cherry-pick)

| Area | #394 contribution | Canonical treatment in #395 |
| --- | --- | --- |
| ES dates | Event + Timeline nested date filters; year/month period overlap | Equivalent query retained in `query_body.py` with shared `event_time.py`, plus hour/minute/second and offset-safe UTC candidate widening |
| Source block scope | Top-level multidim `event_id` is local, not document-global | Source and inner hits correlated to block index; **undated event IDs also reserve that ID**, so offset-less inner hits cannot borrow another block's date |
| Parenthesized days | Codex found fabricated January 1 and first-match collision for `今(1)日` | Explicit linked Event intervals take precedence; no inferred day from year/month boundary or arbitrary first matching month. Dedicated tests migrated |
| Ambiguous evidence | #394 may retain undated background evidence in date-filtered results | #395 deliberately excludes unmatched/unknown-date Evidence from **date-qualified** results; no unproved inclusion in period summaries |
| Citation contract | `date_window` / `date_unresolved` | One provenance model, `event_time_candidates` and `matched_event_time_candidates`; `tp/times` survive LLM compaction. No second incompatible public schema |
| Report statistics | Replace publication-date-first fallback | Count only query-matched day-level Event dates; partial periods do not become an artificial daily count |
| Legacy date shapes | #394 inferred unknown precision from date shape | #395 infers when precision is missing/empty, but explicit `unknown` is intentionally **not** asserted exact |
| Review / CI | #394 has targeted synthetic tests and unresolved Codex P1/P2 | Migrate non-redundant regressions, re-run Python 3.10/3.11 and other required checks on the final #395 head |

## Regression and known issue transfer

#394's Codex P1: inner_hits without outer-block identity could connect one
block's `E1` to a different block's dated `E1`, **including when the first
`E1` had no date at all**. The integrated parser counts ID declarations in
each block independent of time validity; when inner_hit offset is unavailable,
the cited IDs must all resolve uniquely within the *same* block or stay
undated. It never promotes a document-level Event candidate into proof that
the citation belongs to that Event.

#394's Codex P2: `今(1)日` with both March 1 and June 1 links must not
arbitrarily choose March 1 or fabricate January 1 for a year-only record.
Retain linked candidates and use their period intersection instead.

#395's Codex P2: legacy missing/empty `time_precision` plus a timestamp
with explicit timezone offset might be indexed by ES on an adjacent UTC day.
The dedicated legacy branch uses a conservatively widened **year-wide**
date candidate range (one extra UTC boundary day on each side): an absent
precision can encode \`YYYY\`, \`YYYY-MM\`, a literal day, or an offset-bearing
timestamp, and ES mapping cannot infer its source granularity. The Evidence
stage checks original period and event link. This is safe but can be broader
than a specific-day ES search, so realistic read-only performance is a
separate operator gate.

Other regressions preserved: Event-only with empty Timeline; Timeline-only;
nonmatching dates; multiple Event IDs; invalid precision; hour/minute/second;
duplicate IDs; multi-block inner hits; publication-vs-event conflicts;
report compression and final citations; day/month/quarter deduplication.

## Explicit behavioral boundary

Some #394 tests allowed an explicit date in snippet text to supersede a
different valid structured Event date. In the integrated P0, a known linked
Event date remains authoritative for **date retrieval**. A separate timestamp
explicitly present in Evidence text can be independently preserved only when
the structured link has no resolvable date. Representing two independently
dated facts in one citation requires an additional extraction/source schema
decision and must **not** be silently approximated by overriding either date.

Similarly, #394 admitted undated background snippets as weak evidence for a
date-scoped document. The integrated path fail-closes: a dated Event in a
document does not prove undated background evidence occurred on that date.
Both behaviors are explicit decisions; neither is an automatic merge artifact.

## Release gate

- [ ] One consolidated code path with both PRs' relevant regressions passing
- [ ] All latest-head hosted CI successful; no stale-head PASS reuse
- [ ] Independent formal Codex review on that same head, zero unresolved P1/P2
- [x] Close #394 without merge; retain its historical branch and review record
- [ ] Merge only canonical #395 once every P0 gate passes
- [ ] **Real private `news_test` ES Mapping, time-zone, _nested offsets, and
      operator report/LLM/DOCX flows remain NOT TESTED.** No live writes,
      reprocessing, service restart or Mapping migration is authorized here.
- [ ] Keep [Issue #393](https://github.com/hun186/poc-agent/issues/393)
      open for live acceptance even after a reviewed code merge.
