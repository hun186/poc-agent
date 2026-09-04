# SRA Batch Scheduler Phase 1 operations

The scheduler is a standalone HTTP client. It never imports the Agent, queries Elasticsearch, invokes the server worker, renders Word, or accesses the server Report Job database.

## Credential and configuration

Create a dedicated key with exactly the three scheduler scopes:

```bash
python -m api.security.cli create-service-key \
  --name batch-scheduler-production \
  --scope report:job:create \
  --scope report:job:read \
  --scope report:job:download
```

Copy the returned value once into `SRA_BATCH_SERVICE_KEY` in runtime secret configuration. Never commit it or place it in scheduler inputs. Configure `SRA_API_BASE`, `SRA_BATCH_DB_PATH`, and `SRA_BATCH_OUTPUT_ROOT`; optional polling, connect/read timeout, and retry variables are documented in `.env.example`.

## Inputs

CSV/XLSX use this header (XLSX uses the first worksheet):

```text
task_id,prompt,filename,session_id,model,scheduled_at,metadata_json
```

Example CSV row:

```csv
task_id,prompt,filename,session_id,model,scheduled_at,metadata_json
report-1,Prepare the report,report-1.docx,,SRA-Structured Retrieval Agent,2026-09-04T18:00:00+08:00,"{""department"":""analysis""}"
```

JSON may be a task array or an envelope:

```json
{"batch_id":"daily-20260904","tasks":[{"task_id":"report-2","prompt":"Prepare the second report","metadata":{"department":"analysis"}}]}
```

Times must contain an offset. `.xls`, recurrence/cron, unknown fields, duplicate IDs, and non-object metadata are rejected.

## Workflow

```bash
python -m batch_scheduler validate tasks.csv
python -m batch_scheduler import tasks.csv --batch-id daily-20260904 --output-dir ./reports
python -m batch_scheduler run daily-20260904
python -m batch_scheduler status daily-20260904 --json
python -m batch_scheduler resume daily-20260904
# import and run together
python -m batch_scheduler execute tasks.json --batch-id adhoc-20260904 --output-dir ./reports
```

Exit codes are 0 success, 1 unexpected/runtime failure, 2 validation/not-found/configuration failure, 3 completed with task failures, and 4 credential rejection. `resume` reconciles persisted work; a task's deterministic Idempotency-Key is reused after the POST acceptance crash window.

## Security, durability, and limits

Downloads ignore remote filenames, remain confined beneath the configured output root, validate DOCX ZIP members, fsync a temporary file, and atomically rename without overwriting an existing artifact. Back up the scheduler SQLite database and output directory together and define retention policy for both.

The SRA Report Job backend is currently single-machine/single-API-process. Remote `failed` or `interrupted` jobs are terminal and are not automatically resubmitted in Phase 1. There is no cron/recurrence, cancel/retry endpoint, server dashboard, or Windows GUI. HTTP reads remain short because long report generation runs asynchronously on the server.
