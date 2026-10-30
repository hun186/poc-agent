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

## Authenticated browser UI (follow-up to #334)

- Open `/report-jobs` or use the existing editor navigation item. This is a **static UI**, not an alternative job queue or new authenticated API. It calls the existing `POST /v1/report/jobs`, owner-scoped `GET /v1/report/jobs/{id}`, and authenticated `GET /v1/report/jobs/{id}/word`.
- Enter a Report Job authorized Bearer Token in the password input. It stays in the current page's input field only; no cookie, URL, localStorage or sessionStorage write, no URL bearer download. Required scopes: `report:job:create` to submit, `report:job:read` to poll, and `report:job:download` to retrieve final DOCX; owner mismatch deliberately remains 404. Do not use the page on plain HTTP across untrusted networks; use HTTPS or a trusted local channel.
- The user may submit one real report or paste an existing Job ID. The browser polls every 3 seconds only while visible, has a Stop control that **does not cancel the server job**, and stops on terminal statuses. Offline/server errors preserve the last successful phase as stale evidence and retry after 10s; no automatic POST retry or duplicate submission. A lost POST response means unknown creation state and requires manual reconciliation.
- Only fixed phase/status/observation/failure-category labels are rendered via textContent. `long_running` is an observation, not a server timeout or GPU-queue metric. Auth failures stop polling; Word is fetched with the same Bearer auth and provided as an in-browser blob download only after `completed`. Missing or invalid artifacts remain server-validated.
- Hosted Node VM test uses synthetic HTTP responses and checks UI behavior and security boundaries; Hosted Python static-route tests verify asset delivery and headers. These are **not** real browser/production Ollama/ES/SQL E2E evidence. Browser visual screenshot and live provider acceptance are deferred to an authorized deployed environment.

- 2026-10-30 Codex P2 filename correction: authenticated GET /word Content-Disposition filename or RFC 5987 UTF-8 filename* determines the blob download's filename. Reject invalid/non-DOCX/path-like disposition values and use safe `report-<job_id>.docx` fallback; do not pass bearer in the URL. Node tests cover plain quoted, UTF-8, malicious path, malformed encoding, and absent headers. Hosted CI and final-HEAD formal review remain required; no private Linux/browser acceptance implied.
