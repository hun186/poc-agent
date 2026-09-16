# Requirement Automatic Operator E2E Harness Design v2

## Document control

- Repository: `hun186/poc-agent`
- Branch: `work`
- Authoritative hosted baseline: `919422bce992e757a89767f66beb8e042707a976`
- Design version: v2
- Supersedes: Requirement Automatic Operator E2E Harness Design v1
- Status: implementation authority

## Architecture

One `Harness` owns the unchanged Requirement → Schedule → Handoff → Report Job golden path.
It receives one narrow deployment-evidence provider. `local` obtains Linux `/proc`, launcher
identity, Git/worktree, artifact-root, and artifact-byte evidence directly. `remote` obtains the
same deployment assertions from authenticated `GET /v1/operator-e2e/runtime-evidence`, then
downloads each real Report Job DOCX through the existing `/v1/report/jobs/{job_id}/word` route.
There are no local/remote copies of functional orchestration.

## Trust and source authority

`SRA_E2E_EXPECTED_RUNTIME_SHA` is mandatory and externally reviewed. The clean operator Harness
checkout and deployment runtime identity must both equal it. A remote workstation never
self-attests deployment identity. The deployment endpoint computes Git identity and worker
identity on Linux using the launcher identity records and existing positive PID/start-time/UID/
cwd/cmdline rules. Package/overlay identity is blocked unless an approved authority can prove it.

## Artifact and credential boundaries

Local mode retains direct, root-confined filesystem validation. Remote mode uses the existing
superuser-capable Report Job download authorization and independently validates downloaded ZIP
members and SHA-256. The endpoint returns only a root fingerprint derived from
`REQUIREMENT_HANDOFF_OUTPUT_ROOT`; it never returns the path. It is editor-session authenticated,
superuser protected, read-only, and returns no credentials, environment, PIDs, cwd, cmdline,
prompts, or SQL configuration.

## Contracts

- CLI modes: `local` (default) and `remote`; there is no auto/fallback mode.
- Canonical default input is `operator_e2e/input/requirement_e2e_3items.xlsx`, resolved from the
  script directory and automatically bound to its known digest.
- Results use `requirement_e2e_result_v2` with execution mode, operator/deployment source,
  deployment evidence, input, fixtures, import, schedule, batch, items, and artifacts.
- Infrastructure evidence failures are fail-closed categories, never warnings.
- A PASS in either mode is independently complete. A remote failure preserves evidence and does
  not launch local mode.
- POSIX uses `fcntl`; remote Windows uses `msvcrt` only for checkout/output-local concurrency.
  This is not a distributed multi-operator lock; fixture drift and immutable run identity remain
  the interference safeguards.

## Security and non-goals

The evidence surface cannot mutate SQL, workers, schedules, snapshots, checkpoints, or artifacts.
No scheduler, Handoff, Report Job, Agent, Elasticsearch, LLM, or DOCX semantics change. No UI,
LangGraph, JT-1, automatic mode detection/fallback, distributed lock schema, or worker-control API
is introduced.
