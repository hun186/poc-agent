# ARC deep same-PIT frequency transport

Default off. The trusted N-round executor can request an optional count-only
aggregation after the entire canonical page chain, using the latest PIT
identity. The worker binding must provide an independent explicit
`check_frequency_scope` policy, in addition to the normal live owner/index/
branch policy. Existing production composition does not install that policy.

Both `SRAF_ARC_DEEP_FREQUENCY=shadow` and
`SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX` (one concrete, operator-verified
index with appropriate mapping/analyzer) must be configured. This is an
operator attestation, not automatic verification of aliases or permissions.
The adapter verifies unchanged date/entity filter DSL; no caller DSL, no
additional PIT open, no relevance shoulds, no source or hit rows, no model
call. Only the original semantic groups are counted. Same-PIT consistency is
per round, not across rounds. Counts are root documents matching analyzer-
dependent predicates, not canonical event Evidence or semantic recall.

Shared ARC and main admission budgets apply. One additional ES call per
round, at most two per request; retain two ES slots and ten seconds of
retrieval budget at admission. Server timeout 2s, transport timeout at most
3s, no retries. Optional denial or invalid/partial count response does not
replace the canonical result. Adopt a valid returned PIT id before parsing
counts and close the latest known id even on count failure. An explicitly
malformed replacement id or failed close fails the main technical receipt
rather than asserting verified cleanup. A transport exception may conceal a
server-side PIT rotation; only the latest known id can be closed, with PIT
keepalive expiration as the remaining server-side limit. No guarantee of
in-flight cancellation. Recheck owner and independent frequency policy
after cleanup; discard counts if changed/expired. Only fixed count/ordinal
logs; no changes to public audit, Evidence selection, ranking, Word, or
semantic coverage.

Synthetic regression tests are submitted. No actual private Elasticsearch
request, production policy enablement, mapping/analyzer or latency test is
claimed. Next: explicit production authorization and private A/B acceptance;
do not enable by default.
