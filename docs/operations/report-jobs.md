# Report Jobs Operations

| Variable | Default | Purpose |
| --- | --- | --- |
| `REPORT_JOBS_DB_PATH` | `.api_jobs/jobs.sqlite3` | SQLite metadata location |
| `REPORT_JOBS_REPORTS_ROOT` | `.api_jobs/reports` | local final DOCX directory |
| `REPORT_JOBS_SQLITE_BUSY_TIMEOUT_MS` | `5000` | lock wait per connection |

Use one API process for this phase. Multiple processes would each start a worker and local files are not shared or replicated. Back up/retain SQLite and reports together, and establish an external retention policy.

On startup stale `running` jobs become `interrupted`; they are not retried automatically. Submit a new job (and use a new idempotency key) after operational review. A process crash can occur after model side effects but before completion is recorded, so exactly-once is not promised.

For the synchronous endpoint, configure Nginx `proxy_read_timeout` and upstream timeouts above the maximum expected generation time. Prefer Job API polling for longer reports.

If download reports a completed-but-unavailable artifact, verify the reports root is mounted, readable by the service account, and retained alongside SQLite. Do not edit `docx_basename`; the server only accepts `<job_id>.docx` and validates it as a ZIP/DOCX container.
