# ARC A8 measured optional model attempt

Set SRAF_ARC_REVIEW_RESOURCE_METRICS=shadow only in the already authorized
A8 shadow path. Default off. Logs SRAF_ARC_REVIEW_RESOURCE with an isolated
measurement object compatible with A9 resource evaluation. Measures monotonic
elapsed time for the actual adapter invocation, including parsing; llm_calls
counts an attempted session.post invocation, not an ARC reservation or proof
that a server accepted the request. No ES call here. No retry.

The status completed requires a valid semantic verdict summary; failed includes
malformed/rejected responses, timed_out covers Requests timeout or the existing
cooperative elapsed limit. Prompt/completion tokens are only the validated
provider-reported prompt_eval_count/eval_count from a complete assistant
envelope; missing or malformed values are null, never estimated. These are
provider-reported usage, not independently verified billing counts.

No log if transport was not attempted, the initial authorization failed or
post-call permission/deadline changed. No identifiers, endpoint, source text,
raw provider content or per-row verdicts in the measurement. Therefore these
logs alone are not a complete all-attempt report across revoked scopes.
No full-report instrumentation or baseline pairing yet; operator must measure
equivalent scope and preserve failed attempts in private A/B. No production
callback or live private provider measurement performed.
