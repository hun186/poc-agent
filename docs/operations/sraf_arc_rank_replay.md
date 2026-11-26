# ARC A9 offline A4 rank replay

Run on private host only:
```bash
python -m agent.es.evidence_core.arc_eval_cli rank-replay PRIVATE_RANK_CASES.json
```
The local file is an array of cases, each containing exactly groups (lists of
aliases in original group order), frequency (the matching A3/A3b observation
with the schema/scope expected by A4), and rows (the original ordered strict
Evidence prefix). Each row contains exactly text, source (case-local source
ordinal), group_hits, weak (boolean), direct_anchor (operator-confirmed
boolean), and gold (relevant/uncertain/unrelated). No ES IDs. Use 21–128
rows per case, max 4096 chars per row, 131072 chars per case and 1 Mi chars
total. Existing CLI 2 MiB input limit and max 32 cases/4096 rows apply.

Replay uses the same A4 ranking implementation and per-case ARC reservation,
not a separate score implementation. Local ordinal ranks are paired only
in memory and passed to A9 selection evaluator. Emits aggregate full and
top-20 quality comparisons; production observer still emits only counts.
No ES, model, or mutation. Operator must independently freeze the original
strict prefix and matching frequency from the same retrieval, annotate
every row and confirm source/anchor identity. The input cannot prove real
snapshot identity or canonical date eligibility; not a corpus-recall or
full production A/B claim. Do not commit private input files. This is
rank-only replay; A5/A6 and capture automation remain pending.


## Actual report count-limit replay

An optional case field `report_selection` may be supplied:

```json
{"scope":"complete_report_input_strong_first","limit":120}
```

The operator must attest that the ordered rows are the complete input to
the report's legacy strong-first selection (21–128 rows), not an arbitrary
prefix or one search among multiple tools. The limit must be the actual
positive report count limit, up to 128. This excludes source-diverse
selection. Both arms use the very same strong-first helper as ReportAgent,
without changing report behavior. The candidate arm applies the existing
A4 rank kernel before that helper. Aggregate report_selection_comparison
measures selected rows at the declared limit separately from raw top-20
diagnostics; report_selection_limit_cases shows the distribution of limits.
Cases without the optional field retain the original evaluation. A gain
at top 20 can disappear when a larger report cap includes all rows. This
does not simulate compression, prompt token limits, LLM output, multiple
searches, or source diversity; it cannot attest completeness or authorize
production ranking. No new env variables or model/ES access.
