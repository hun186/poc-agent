# A9 private A6 low-volume relaxation replay

Run on the private host only:

```bash
python -m agent.es.evidence_core.arc_eval_cli relax-replay PRIVATE_RELAX_CASES.json
```

Each input fixture is an object containing exactly case, fixture_digest, and
labels. The case contains the original question (explicit subject), query
used for snippet parsing, original ordered groups (lists of aliases),
date_from/date_to (ISO day bounds), and the actual frozen first-primary ES
response. No new ES query is performed. Both arms use the identical response,
legacy default EvidenceBuildConfig, and canonical date/topic validators.
This does not assert that the original ES query was correct or that its
returned slice exhausts the corpus. Partial/timed-out/shard-incomplete
responses, >128 source hits, ambiguous duplicate canonical identities,
>8 parsed citations per hit, >128 parsed citations, oversized text and
truncated A6 scans are rejected. A lower-bound total may be observed but is
not corpus completeness. No fallback/refill or ambient builder rollout flags
are used.

Private preparation API:
`agent.es.evidence_core.arc_relax_replay.prepare_relax_annotation(case)`.
It returns a fixture_digest and the canonical date-eligible rows (local
ordinal, source ordinal, private text, gold=null) for independent labeling.
Keep it in the private host only; never print raw rows to application logs or
upload to GitHub. Label every row relevant/uncertain/unrelated; construct
labels as a list of {ordinal, gold} and include the unchanged original case
and fixture_digest. The digest binds input and parsed row order to prevent
accidental label reuse after changes, not to prove authorization or
tamper resistance.

Replay uses the exact A6 kernel, which proposes new direct two-axis rows
with the explicit required subject and canonical date eligibility. The
candidate arm keeps every strict row, then appends the first eligible
distinct identities in original scan order, up to min(2, 3-strict_count).
This is an explicitly defined offline counterfactual, not a production
selection rule. A6 currently only logs counts. The result reports aggregate
full/top-20 quality, additions and losses, and the hypothetical added count.
The denominator is the labeled canonical eligible parsed slice, not the
corpus or final report. No ES/LLM calls, no report mutation, no actual
retrieval strategy change. Existing legacy rescue/refill and zero-strict
fallback are not modeled by this comparison. Private data live acceptance
and convenient local annotation file generation remain pending.
