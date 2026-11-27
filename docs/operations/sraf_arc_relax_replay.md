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


## Private annotation file command

Provide an array of unchanged case objects in a private local directory:

```bash
python -m agent.es.evidence_core.arc_relax_annotation_cli PRIVATE_CASES.json PRIVATE_ANNOTATION.json
python -m agent.es.evidence_core.arc_eval_cli relax-replay PRIVATE_ANNOTATION.json
```

Between these commands, independently edit each label's gold from null to
relevant, uncertain or unrelated. Leave every other field unchanged. The
human-readable label text and local source ordinal are rechecked against
the recomputed canonical row; older compact ordinal/gold labels remain
valid. Output includes the original raw response and private text; never
upload or commit it. The preparation command creates an exclusive new file
(no overwrite), uses owner-only initial mode on POSIX, and requires an
already private directory ACL on Windows. It emits only count/status JSON
to stdout. A failed write may leave a partial file, never treated as valid.
Input and generated output are each limited to 2 MiB. No ES/LLM calls.


## Narrow A6 pilot preparation (offline, not activation)

The original strict-only counterfactual remains a diagnostic and includes
zero-strict cases. It must not be used as proof that the real legacy
zero-strict fallback is inferior. The narrower pilot candidate preparation
reuses the same bounded A6 scan and requires 1–2 strict rows, an exact
exhausted primary result (total equals returned), an untruncated parsed
scan, an explicit ISO date window, and a strong strict row carrying the
explicit required subject and a linked matched event date. Each of the
first proposed additions must carry structured linked matched event dates;
otherwise the whole pilot proposal is rejected rather than choosing a
different ordering. Prepared additions are new EvidenceSnippet objects,
marked adaptive_two_axis, text scope, two matched groups and weak evidence.
They preserve the canonical dates, source ordinal, block and event identity.
No mutation of existing strict rows.

The existing relax-replay output retains the broad comparison and adds a
separate pilot_status_counts and pilot_comparison (null if no eligible
cases). Pilot comparison is only the eligible subset of operator-frozen
legacy-parser cases. It does not compare the entire production pipeline,
other rescue modes, final report selection or actual measured resources.
A successful candidate preparation is not authority to activate it. The
ordinary report integration, live authorization, compatible rescue policy,
quality/resource acceptance and explicit rollout remain independent gates.
No new env flag, no production builder call and no live data access.


## Actual builder and final-selection parity check

Labeled relax-replay now also executes both the existing builder baseline
and a private, explicitly requested offline A6 candidate build, through
the real date-refill final selection. This runs only on the previously
eligible exhausted primary cases. No network or additional page is allowed;
the declared result limit equals the number of returned primary hits,
not a claim about the original production request's size. The baseline
must exactly match the strict-only identities. Candidate output must
retain the entire serialized baseline prefix and exactly append the
expected weak linked-event rows, and final selection must preserve the
builder's rows. The offline pilot is refused when rescue, legacy topic
adaptive, a nondefault builder configuration, acceptance/capture scope,
or missing shared budget would make the comparison unsafe.

The aggregate output includes pipeline_status_counts and pipeline_comparison
(null without verified parity). Broad counterfactual and narrow pilot
metrics remain separate. An incompatible environment, unexpected page,
or failed parity check does not count as a successful pipeline case.
This is an offline explicit Python entry only; no production caller or
environment flag activates it. It can be tested with ARC master off
without changing normal production behavior. No live quality/resource
approval, no full-report LLM or Word generation, and no rollout authority.


## Single-command measured offline acceptance

Run on a private host in a dedicated process, with ARC observations off:

```bash
SRAF_ARC_MODE=off python -m agent.es.evidence_core.arc_eval_cli relax-acceptance PRIVATE_ACCEPTANCE.json
```

The input object contains policy (the explicit A9 acceptance policy in
sraf_arc_acceptance_screen.md) and cases (the same independently labeled
fixtures consumed by relax-replay). No manual rank or resource measurement
entry is required. The program derives exact paired ranks, validates
builder/final selection parity, and measures monotonic wall-clock elapsed
milliseconds for each actual offline builder/refill invocation. Exact
duplicate fixtures are rejected. Ineligible cases remain in the denominator
and prevent acceptance; failed attempts remain in the resource comparison.
The baseline executes first; timing is a single paired observation and
can be affected by cache, logging and machine load. No full report latency,
network, token budget or LLM quality is measured. ES/LLM calls and tokens
are zero ONLY within this no-provider-IO boundary.

All supplied cases must have pipeline parity before the existing
conservative quality/resource policy is evaluated. BLOCKED indicates a
pipeline failure or policy violation; INCOMPLETE includes missing
eligibility or configuration. MEETS_OFFLINE_THRESHOLDS does not authorize
production. CLI exit 0 means an evaluation was returned, not acceptance.
Private fixtures stay local; output is aggregate only. No new environment
setting or activation of production ARC selection.
