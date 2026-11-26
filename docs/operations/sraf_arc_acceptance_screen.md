# ARC A9 conservative offline acceptance screen

Run locally with the existing paired selection and measured resource records:

```bash
python -m agent.es.evidence_core.arc_eval_cli acceptance PRIVATE_ACCEPTANCE.json
```

The object contains policy and cases. Each case contains selection (the
existing A9 paired local ordinal/rank labels) and resources (baseline and
candidate observed measurement objects). The operator must ensure both
arms use the same case, snapshot, workload, measurement boundary and
independent human labels. Do not substitute budget reservations, sample
counts or estimated tokens for actual measurements.

Policy must specify all fields: minimum_cases (1–32), 
min_full_precision_delta_bps and min_top20_precision_delta_bps (signed
basis-point change, -10000 to 10000), min_net_relevant_gain (nonnegative
integer aggregate), max_elapsed_increase_ms, max_es_call_increase,
max_llm_call_increase, max_prompt_token_increase, and
max_completion_token_increase (nonnegative per-case increases).
No default policy or rollout permission is supplied.

The screen blocks full relevant/uncertain removals, any full/top20
relevant anchor/strong/source loss, top20 relevant count regressions,
jointly incomplete attempts, case-level precision or resource policy
violations and inadequate aggregate relevant gain. Unknown token usage,
undefined known-label precision, changed uncertain selection, no baseline
relevant evidence or insufficient case count prevent a positive screen.
Precision comparison uses exact fractions; averages cannot compensate
for individual resource/quality regressions.

Result is BLOCKED, INCOMPLETE or MEETS_OFFLINE_THRESHOLDS, with fixed
count-only reasons and the existing aggregate comparisons. The latter
means only the supplied sample met the chosen conservative policy, never
production authorization. production_authorized is always false. The CLI
exit 0 means evaluation performed, not an acceptance pass. No automatic
flag changes, deployment, corpus recall or live evaluation. This screen
intentionally may reject beneficial strategies that trade different
relevant rows; any different safety policy requires independent review.
