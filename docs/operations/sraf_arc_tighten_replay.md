# A9 offline A5 tightening replay

Private local Python entry point: agent.es.evidence_core.arc_tighten_replay.replay_tightening_cases(cases). CLI wiring follows the independent rank replay change.

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
