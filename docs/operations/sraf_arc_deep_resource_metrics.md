# ARC A9 deep retrieval resource measurements

Default off. SRAF_ARC_DEEP_RESOURCE_METRICS=shadow creates one private
measurement scope per trusted N-round retrieval execution. Counts actual
SDK method invocations (PIT open, canonical search page, optional same-PIT
DF search, PIT close). Failed invocations and mandatory close are counted,
but denied admissions or failed options construction are not. No changes
to admission, query, evidence, or result. Separate from budget reservations.

The elapsed monotonic duration includes the retrieval loop, planner and
semantic callbacks, checkpointing and cleanup. A sufficient trusted
retrieval returns completed; other returned terminal reasons count as failed
or cancelled, and exceptions count as failed, even when the coordinator is
subsequently cancelled. This is not a full Word-generation measurement.
No inferred LLM calls or tokens: these fields remain null until actual
transport instrumentation can cover the complete boundary. SDK invocations
are not proof of wire-level requests or provider success. An isolated
optional model metrics record is not a substitute for total LLM usage.

SRAF_ARC_DEEP_RETRIEVAL_RESOURCE logs one count-only object with a resource
measurement compatible with A9 and a breakdown by operation. No IDs,
question, endpoint or text. The observer is context-local, coordinator-bound,
and reset on completion/failure. No new public API or durable job telemetry.
Operator must pair equivalent private workload and measurement scope.
Synthetic tests only; no private ES/LLM requests or production deployment.
