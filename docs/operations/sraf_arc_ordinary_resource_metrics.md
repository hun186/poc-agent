# Ordinary report resource observation

Default off. Set SRAF_ARC_ORDINARY_RESOURCE_METRICS=shadow on the existing
ordinary report path to collect a sealed count-only observation around
ask_with_report, from query refinement through synthesis. It excludes
outer routing, Word export, scheduling and the separate N-round path.
Requirement E2E acceptance is excluded. Each report owns its own scope,
propagated explicitly to existing per-agent ES tool instances. A sealed
collector rejects late attempts and usage.

SRAF_ARC_ORDINARY_RESOURCE logs elapsed monotonic milliseconds, returned
or raised (not a report correctness verdict), adapter invocation counts
for safe_search, highlight retry, optional native frequency, Ollama
chat/generate and the existing observed Data Agent generate boundary.
Attempts include adapter exceptions, not merely budget reservations.
No claim that an SDK invocation equals one wire request; SDK retries and
other transport paths are not measured. Data Agent generate is a model
boundary, not an observed HTTP request. Ollama usage is the sum of valid
provider counts from complete decoded responses with known-attempt
counts per metric; missing counts remain unknown, not zero. It is not
total report tokens, since LiteLLM usage and uninstrumented paths are
not included. complete_transport_totals is always false. Do not pass
this partial record off as a complete A9 resource measurement.

No raw content, model, endpoint, index or report IDs are added to the
new log. No new provider requests, query changes, evidence selection,
authorization or API fields. Existing transport behavior is preserved.
Synthetic adapter and worker-thread regressions only; actual private
report measurements and complete resource coverage remain pending.
