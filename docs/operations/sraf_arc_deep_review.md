# ARC A8 deep round review pilot

Default off, no production worker policy installed. The trusted N-round
executor may invoke the dedicated A8 HTTPS transport after the original
semantic assessor completes and before the round is committed. It reviews
only the report-approved rows for this round (not the final whole-report
selection), never changes the witnesses, report rows, rank or coverage.
The main owner/index/branch policy must remain authorized before completing
the round, even if the optional egress policy revokes during the review.

Required configuration: SRAF_ARC_REVIEW_DEEP=shadow, SRAF_ARC_REVIEW=shadow,
SRAF_ARC_REVIEW_EGRESS=approved, exact verified concrete index, dedicated
HTTPS endpoint, model and validated TLS trust. The trusted Worker must
explicitly inject check_review_egress(job, constraints, index, source_ids,
endpoint, model, verify) that independently authorizes the original question,
semantic groups, all listed source documents, actual data egress/retention
policy and resolved endpoint/model/CA. The environment alone cannot grant
access; no callback is provided by existing production composition. The
transport now requires an explicit authorization callback on every request;
no implicit authorization for standalone calls.

A narrow pilot requires one complete attested round, one concrete index,
1–128 raw sources, at least 40 report-approved rows, the first 64 of those
rows (existing grant order, not relevance sorting), strict policy, valid
structured matched event times, citeable row and <=1500 whole-text chars.
At least four eligible distinct selected sources and some weak/mixed
ambiguity are needed. The scan consumes a shared ARC reservation before
text preparation, then the existing A8 sampler makes a maximum eight-source
batch. Independent policy must approve every possible source in that prefix,
a conservative superset of the actual model batch. Exact source IDs are
derived from the attested ES hit digests, never application UUIDs. Only
bounded source IDs are retained privately; clear after review/terminal
error. No raw source ID, endpoint, model, text or result is logged.
Before and after model callback check actual owner/source/endpoint permission
and at least 25s beyond generation reserve; one nonrefundable ARC LLM slot,
no retries or alternate provider. Requests read timeout is not a hard
end-to-end deadline and in-flight calls cannot be recalled. Egress denial
or invalid model result alone abstains; loss of main owner authorization
still fails closed. A8 observation cannot grant or revoke a semantic
witness. Counts from a biased sample of already-approved rows are not
accuracy measurements. The ordinary A2/A7/A8 allocator and ordinary
source-level grant still require integration. Synthetic tests only, no
actual private model transmission, owner ACL policy implementation,
deployment or live acceptance claimed.
