# SRAF launcher reports API readiness timed out

## What this means

`run_sra_api.sh` starts Uvicorn first and waits up to
`API_READINESS_TIMEOUT_SECONDS` (default 90s) for the recorded API process to
own a listening socket on its configured port. Only after that does it launch
the Requirement Schedule and Handoff workers. Therefore empty worker logs
after readiness timeout are **expected**, not proof of independent worker
failure. A Uvicorn log ending at `Waiting for application startup.` means
its FastAPI lifespan has not reached the point where the server starts listening.

On a newly updated host, first record versions, preserve current logs (launcher
truncates ordinary logs on next run), and verify the actual release files were
overlaid consistently. An archive extraction message alone is not a manifest
or deployment-integrity proof. Do not reset the databases or remove PID/lock
files to get past this state.

## Safe first checks (no tokens or connection strings)

From the deployed repository root:

```sh
# Run BEFORE retrying the launcher; a retry truncates these three log files.
tail -n 80 SRA-API_output.txt
ss -ltn '( sport = :9002 )'
python - <<'PY'
from config.bootstrap import bootstrap_env
bootstrap_env()
import os
for key in (
    "REQUIREMENT_E2E_EXTERNAL_MODE",
    "REQUIREMENT_PIPELINE_ENABLED",
    "REQUIREMENT_SCHEDULER_ENABLED",
):
    print(f"{key}={os.environ.get(key) or '<unset>'}")
PY
```

The three printed settings are non-secret mode/feature flags. Never paste the
whole `.env.*`, `env`, SQL registry, API tokens or full exception payload.

If `REQUIREMENT_E2E_EXTERNAL_MODE` is `live` or `auto`,
`frozen_plan(resolve_environment_plan)` performs real model and Elasticsearch
probes during API lifespan. A blocked model or external service can hold
startup. When Requirement or Schedule is enabled, the corresponding SQL Server
store initialization is also synchronous and may wait on a connection or
database lock. Report Job SQLite initialization/recovery can also wait.
Do not disable these production functions to create a misleading green check.

## Checkpoints available after this change is deployed

`SRA-API_output.txt` logs only enumerated non-sensitive stage names and
monotonic elapsed milliseconds under the `SRA_STARTUP` prefix:

```sh
grep 'SRA_STARTUP' SRA-API_output.txt
```

The last `phase=...begin` without its matching `phase=...done` identifies
the operation in progress when startup stopped. In particular:

| Last checkpoint | Investigate |
| --- | --- |
| `external_plan.begin` | Real LLM/Agent/Elasticsearch capability probes |
| `requirement_store.begin` | SQL Server Requirement connection, schema, permissions or lock |
| `schedule_store.begin` | SQL Server Schedule connection, migrations or lock |
| `report_store.begin` | Local Report Job SQLite open/migration/lock |
| `report_recovery.begin` | SQLite interrupted-job recovery |
| `report_worker.begin` | Worker thread startup and report directory permissions |

A completed `lifespan.ready` means the code finished lifespan initialization,
but does **not** by itself prove the API is listening, healthy, or that the
Schedule/Handoff workers are running. Continue with actual listener/health,
Worker identity and operator-authorized SQL/Report Job probes. This logging
change changes neither startup order nor failure behavior, does not increase
timeouts, and cannot fix a blocked dependency on its own.

Avoid printing secrets, killing arbitrary port owners, deleting .api_jobs files
or bypassing TLS to make the startup indicator green.
