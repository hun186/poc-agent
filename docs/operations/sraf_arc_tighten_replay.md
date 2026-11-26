# A9 offline A5 tightening replay

Run on the private host:
```bash
python -m agent.es.evidence_core.arc_eval_cli tighten-replay PRIVATE_TIGHTEN_CASES.json
```
The same aggregate-only CLI file-size, strict parsing and privacy bounds apply.
The private local Python entry point is
agent.es.evidence_core.arc_tighten_replay.replay_tightening_cases(cases).

Each case contains groups (original ordered lists of aliases), question (original
explicit subject marker), pressure ({relation: eq/gte, total: >=256, returned:
positive actual hit count}), local_frequency and native_frequency (matching
A3/A3b count observations or null), and rows (40–128 ordered strict
canonical Evidence rows). Each row contains text, source (actual local hit
ordinal within returned), group_hits (3..number of groups), weak (boolean),
and gold (relevant/uncertain/unrelated). Source ordinals are case-local.
Row and total text caps mirror the A5 kernel and offline replay budget.
No real ES identifiers in fixtures.

The replay reuses the exact A5 selection kernel, collecting private local
positions only in the offline path. For each applicable strategy separately,
derive paired baseline/candidate ranks and compute A9 full and top-20
metrics, including relevant, anchor, strong, and source losses. Cases with
unavailable frequency axes are not counted as zero-result strategies.
Cases below the retained sample floor remain visible as counterfactuals;
no automatic selection or recommendation. The anchor flag comes from the
same explicit literal matcher as A5, not an operator guess. Source/date
eligibility and same-snapshot fixture completeness must still be verified
by the operator. No ES/model calls or production mutation; no real private
A/B has been run.


## Guarded report-selection replay

Optional `report_selection` field: `{"scope":"complete_report_input_strong_first","limit":120}`.
The operator must attest that the 40–128 ordered rows are the complete
input to the report's legacy strong-first count cap, not just a search
prefix or one tool's result in a larger report. Use the actual positive
limit (1–128); source-diverse mode is outside this replay's scope.
Both arms use the same strong-first report helper as A4 replay. For each
applicable A5 strategy, if its existing 20-row/8-source sample floor
fails, the guarded candidate uses the unchanged baseline input. Otherwise
the selected positions from the actual A5 kernel feed the count cap.
The original unguarded prefix counterfactual remains available for diagnosis.

Per-strategy report_selection_comparison measures the capped selection
separately; report_selection_cases and report_floor_fallback_cases expose
the denominator and abstentions. report_selection_limit_cases lists the
declared limits. Missing report scope yields null report comparison.
Passing the count/source floor does not protect every relevant passage:
inspect relevant/anchor/strong/source losses at the actual report limit.
No real date/source authorization, completeness attestation, compression,
token budget, model output, live selection or rollout authority is inferred.
This change depends on the shared report helper introduced in PR #571;
merge that reviewed parent before retargeting and reviewing this change
against main. No additional env keys or live requests.
