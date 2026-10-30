# SRAF DataAgent / smolagents LiteLLMModel call observation

## Why

The 2026-10-30 PR #332 shared `call_llm()` diagnosis observes router, refiner, report and pure-LLM model calls, **not** `agent/data_agent/builder.py`'s independent `smolagents.LiteLLMModel` boundary. The operator confirmed Ollama runs in a separate container from SRAF and a short API-container process survey cannot observe that service. Under heavy unrelated batch inference the SRAF API had startup trouble before PR #319 removed operator live LLM/ES probes from ordinary lifespan startup. This evidence supports *possible* shared model contention; it does **not** prove GPU queuing.

## What this PR does

- `build_model()` keeps the **same real smolagents LiteLLMModel object, type, settings and cached singleton**; in `observe_data_agent_model` only its synchronous `generate` method is wrapped once, preserving positional and keyword args, exact return value and original raised exception.
- Every existing `generate` call inside DataAgent's normal smolagents loop reports a low-cardinality `[llm_call] stage=data_agent outcome=... category=... elapsed_sec=... requests_timeout_sec=unknown` log. Successful calls shorter than 30s are INFO, slow calls 30s or more are WARNING; failures are WARNING. Model ID, URL, request/response text, raw exception and any credentials are **never** logged.
- Error categories use **only actual exception classes**, including Requests and selected LiteLLM timeout, rate-limited, service-unavailable and connection failures. A bounded search of exception cause/context/nested exception arguments detects wrapped transport errors; unknown errors map to `provider_error`. The category alone does not prove an Ollama queue or GPU cause.
- `requests_timeout_sec=unknown` is intentional: the smolagents/LiteLLMModel call path does not expose a single reliable Requests-equivalent timeout or guarantee a hard cancellation deadline. This instrument does **not** introduce a new timeout.
- If a future smolagents implementation has no writable `generate` method, preserve production execution and log `outcome=not_observed category=generate_unavailable|generate_readonly`. Never call it successfully instrumented.
- The synthetic `DeterministicE2ECodeModel` branch remains **unmodified and uninstrumented**, and prior E2E test/nonprod isolation stays as it was; no provider/model traffic is generated as part of this change.

## What this PR does not do

No provider/endpoint reconfiguration, inference requests, job scheduling, retries, Ollama model queue management, new API routes, Report Job status changes or ES/SQL operations. The measured duration is a synchronous **model-generation boundary**; if the model client is nonstreaming, it cannot separate provider queue wait, model load, generation or first-token latency. It does not include the entire report or all DataAgent tool execution.

## Verification

Automated tests use synthetic fake models and errors only, verify unchanged type/response/exception, singleton reuse, mock E2E exclusion, redaction, warning threshold, missing/readonly fallback and error class mapping. Hosted CI must pass the new tests plus the existing API startup/Report Worker/E2E suites and 19 OFF-0 schema checks before formal Codex re-review. Private Linux Ollama response/timeout saturation and real model CPU/GPU contention still require separate operator-authorized evidence, **NOT TESTED** by CI.

After merge and deployment, review pre-existing workload logs for stage=data_agent without adding workload. Compare with [llm_call] stage=router|query_refiner|report|pure_llm emitted by PR #332, accounting for synthetic E2E models and per-stage calls not identical to total Report Job durations.
