# SRAF Report Job progress / wait observation (SQLite v2)

## Purpose

Existing `/v1/report/jobs/{job_id}` returned only `queued/running/completed/failed/interrupted`. Long-running Agent work could be legitimate Ollama/LiteLLM model processing or ES access; a long duration alone **is not evidence** of provider queue, GPU saturation, deadlock or timeout. This change makes real Worker checkpoints readable by the already authenticated **owner-scoped** Job status route. No artificial job success, new jobs, model calls or retry/deadline modifications.

## Database and migration

- Canonical `ReportJobStore` upgrades SQLite schema user_version 1 -> 2 **atomically** using the existing `BEGIN IMMEDIATE`. Legacy version 0 -> 1 -> 2 runs in the same transaction and preserves existing owner-scoped idempotency and prompts. Failure at any migration step rolls back to the original schema. Schema v2 adds `phase TEXT NOT NULL`, `phase_updated_at TEXT` and `failure_category TEXT`. Prior v1 `running` rows backfill `phase=unobserved` rather than pretending we know the Agent's checkpoint; next startup recovers running jobs as `interrupted`.
- New jobs have `phase=queued`. Atomic claim of existing queue sets `phase=agent_execution`. The existing Worker marks `docx_export` only after `execute_agent_turn` has returned, then `finalizing` after real Word byte generation and before fsync/ZIP/atomic artifact publication. Existing `complete`, `fail` and `recover_running` transition phase to `completed/failed/interrupted`, respectively.
- `update_phase` is CAS fenced by `status='running'`; terminal or queued jobs cannot be advanced, and `finalizing` cannot regress to `docx_export`. Existing owner principal and artifact path controls remain unchanged.

## Authenticated status fields (additive)

`GET /v1/report/jobs/{job_id}` remains protected by `REPORT_JOB_READ` and exact owner authorization (or admin scope); cross-owner still returns 404 and keeps its security audit. Existing status, timestamps and sanitized error fields remain. New outer `phase/phase_updated_at/failure_category` are from durable SQLite, while a derived `progress` subobject provides:

- `phase`: `queued | unobserved | agent_execution | docx_export | finalizing | completed | failed | interrupted`
- `elapsed_seconds`: current server-observed monotonic-like wall-clock timestamp **difference** in seconds since `phase_updated_at` for `queued/running`, or `null` if timestamp is unavailable/invalid; never a provider-controlled queue latency.
- `long_running`: true only if active stage duration >=30 seconds; an *attention hint*, not cancellation or timeout.
- `observation`: `active | long_running | duration_unavailable | terminal`; only `terminal` follows a durable terminal Job status.
- `failure_category`: `timeout | rate_limited | provider_unavailable | execution_error | null`, only populated for real failed Jobs from bounded **typed exception/cause** inspection. No exception message or user prompt is serialized. Generic/unrecognized failures remain `execution_error`. A timeout is only classified from a known timeout exception type (including nested `requests.exceptions.Timeout` or known LiteLLM timeout classes), not from 30s warning or elapsed duration.

For browser/UI clients, poll existing status endpoint using existing auth and render e.g. `agent_execution` as **「Agent 分析／檢索中（可能包含模型等待）」**, `docx_export` as **「Word 文件產製中」**, `finalizing` as **「文件寫入與驗證中」**, `long_running` as **「此階段耗時較長，尚未確認逾時」**; for a *real failed timeout* show **「模型／服務呼叫逾時，任務已失敗」** only if `status=failed` and `failure_category=timeout`. Keep `download_url` gated on durable `completed` and existing DOCX validation.

## Limits and safety

- No new endpoint or browser auth store. `progress` is derived from existing authenticated Job state; it cannot see a first token or distinguish Ollama queue wait from model compute, ES, tools and Python. `agent_execution` covers both model and ES calls. The job can be in a hung SDK while `long_running=true` and `status=running`; the HTTP API does not interrupt it.
- Timestamp differences use UTC on the API server and are not hard deadlines. Restart marks an in-flight job `interrupted`; no automatic requeue.
- Tests are synthetic SQLite / fake turn execution + real Word export, plus owner/API regressions. Hosted CI cannot prove private busy Ollama, GPU queue or Linux runtime acceptance. A dedicated visual frontend timeline/polling UX is separate follow-up; existing JSON progress fields are the backend contract, not a claim that a pre-existing GUI has been updated.
