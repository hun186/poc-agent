# ARC A9 paired measured resource evaluation

Local Python API: agent.es.evidence_core.arc_resource_eval.evaluate_resource_cases.
Supply 1–32 paired attempts with baseline and candidate. Each arm contains
status (completed/failed/timed_out/cancelled), elapsed_ms, es_calls, llm_calls,
prompt_tokens, completion_tokens. Each metric is an actual nonnegative integer
measurement or null if unavailable. Use actual transport attempts including
failed calls, not ARC reservations; do not estimate token counts from character
counts. Use the same workload, measurement boundary and timing method in both
arms. No source text, identifiers or other fields.

Returns status transitions and separate all-attempt and jointly completed
subsets. Each metric compares only measured pairs and exposes missing
measurements, paired totals/deltas, relative delta (null for zero baseline),
nearest-rank p50/p95 and case counts. The success subset never substitutes for
all attempts. A missing measurement is not zero, and a lower successful latency
does not offset increased failures. Small-sample percentiles are descriptive
only. This does not collect telemetry, prove pairing or quality, or authorize
deployment; actual instrumented private A/B runs remain pending. No provider,
ES, model or selection changes. CLI wiring may follow separately.
