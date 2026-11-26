# ARC A9 paired full-selection and ranking evaluation

Use evaluate_selection_cases from agent/es/evidence_core/arc_selection_eval.py
on a fixed, privately labeled candidate universe, with a local ordinal
representing each identical passage in both arms. Include the entire union
of the two selections; optional other labeled candidates from the same
universe can have both ranks null. Each row contains ordinal, source
(case-local integer), gold (relevant/uncertain/unrelated), direct_anchor,
strong, baseline_rank and candidate_rank. A null rank means unselected.
Positive ranks must be unique and contiguous within each arm/case.
Maximum 32 cases, 256 rows per case and 4096 total rows. No private text,
real identifiers, or arbitrary extra fields.

Evaluate full selection and top 20 separately. For each arm: known-label
precision, labeled-universe relevant and relevant-source coverage, retained
uncertain count and source count. Paired differences include relevant,
uncertain and unrelated additions/removals, relevant net change, loss
relative to original relevant/anchor/strong evidence, relevant-source loss
and gain, and number of cases losing any relevant row/source. A gain does
not cancel an unrelated loss in these paired indicators. Source ordinals
are scoped per case; retaining irrelevant rows from a lost relevant source
does not count as relevant coverage. Zero denominators are null. No claim
of full-corpus recall: operator must independently establish common snapshot,
candidate-universe completeness, stable row pairing and annotation quality.
No automatic threshold, selection changes or deployment permission.

This is an offline evaluator only. Actual paired private fixture capture,
resource/token/latency measurement and deployment acceptance remain pending.
Existing live count-only diagnostics cannot reconstruct per-row rankings.
