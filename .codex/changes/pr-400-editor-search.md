# SRAF PR #400 — Editor mapping-aware underscore/nested search (OPEN / PERFORMANCE GATED)

## Scope
Fix editor-only search for partial underscore-separated strings such as this_is / a_title from this_is_a_title, with actual Mapping-aware field selection, nested query matching, bounded substring expansion, and conservative exclusion logic. Maintain existing editor authorization and response contracts. This feature does not alter the SRAF Report ES Evidence query planner.

## Operator acceptance gate
Do NOT merge on Hosted success alone. Private news_test mapping/Analyzer behavior, real queries and large-index performance (p50/p95), the impact of leading-wildcard keyword searches, and Elasticsearch search.allow_expensive_queries policy have not been independently verified. Do not turn on unbounded expensive queries or change production Mapping. No private ES data or credentials used by this PR.

## Integration / memory policy
The historical 2026-11-11 archive files under .codex/archive remain preserved. The old-branch replacement of six active .codex memory/contract files was stale and conflicted with new main, so current main's shared memory remains intact and this per-PR change log replaces concurrent edits. On an approved merge, append a separate reviewed final status to canonical project memory.

## Status
Hosted synthetic tests pass, but real performance gate, trusted Mapping check and rollout verification are PENDING. Operator deployment remains Windows -> Linux one-way 7z; do not recommend Linux git fetch.
