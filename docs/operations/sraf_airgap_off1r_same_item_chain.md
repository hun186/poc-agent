# OFF-1R — one SQL-selected item / DOCX / Report Job correlation (partial)

OFF-1R adds an independent, operator-opted **REPORT-CHAIN** row after **REPORT-LIVE PASS**. The earlier OFF-1P and OFF-1Q each queried their own latest scheduled item; if a new run was created between probes their PASS values could refer to different items. OFF-1R narrows this ambiguity with **one seven-field SQL reference** used for both actual local file bytes and authenticated API status, followed by a fresh bounded SQL reference comparison.

## Authorized Linux operator procedure

Set the existing OFF-1G restricted SQL reader credentials (`SRAF_OFF1G_SQL_*`, with strict TLS hostname/IP-SAN verification), `SRAF_OFF1L_SCHEDULE_ID` (canonical `sch_<32 lowercase hex>`), `SRAF_OFF1P_ARTIFACT_ROOT` (approved absolute root), and `SRAF_OFF1Q_REPORT_API_PORT` (a single numeric 127.0.0.1-bound SRAF listener port) plus `SRAF_OFF1Q_REPORT_JOB_READ_TOKEN` (owner-appropriate **REPORT_JOB_READ only** token). Run from the deployment repo root:

```sh
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link --probe-handoff-ack \
  --probe-report-checkpoint --probe-docx-bytes --probe-report-live \
  --probe-report-chain
```

All **ten** flags are necessary; the nine prior results must include actual `REPORT-LIVE: PASS`. With incomplete opt-ins the row is NOT_TESTED; with previous non-PASS the row is SKIP and OFF-1R makes no SQL/HTTP connection. Existing matrix behaviour and non-acceptance status remain unchanged.

OFF-1R pins the operator-authorized output root file descriptor before any SQL query (Linux fd-relative `O_NOFOLLOW` on every ancestor), rejects invalid schedule/schema/root/port/token and missing ODBC Driver18, reads a bounded, parameterized `SELECT TOP (2)` for one latest scheduled batch and one selected completed `report_v1` item. A single row projects batch ID, run-item ID, publisher-relative DOCX filename and SHA-256, published root fingerprint, remote job ID, and handoff submission ID from **the same SQL joined item**. The SELECT joins the Handoff submission on the same run_item_id, requires report_v1 workflow, and checks the Run Item's non-null remote_job_id and dispatched/completed/artifact-reconciled timestamps (the Handoff table itself stores neither remote_job_id nor dispatched_at). References and credentials never enter output JSON.

The original pinned directory descriptor is used to read up to 16 MiB DOCX with no symlinks. The original OFF-1P SHA-256 and ZIP integrity checks run against that *one* selected item. Only after actual file-match does OFF-1R invoke OFF-1Q's fixed authenticated local `GET /v1/report/jobs/{job_id}` with the **same SQL reference**; the API must return the same job ID, `metadata.submission_id`, `metadata.workflow_id=report_v1`, and `status=completed`. OFF-1Q's network caps apply: one 127.0.0.1 TCP request with 3-second absolute total deadline, <=4KiB HTTP header, <=8KiB JSON, no proxy, redirects, retries, gzip or chunked framing. Normal API GET may create audited server-side logs.

After API success OFF-1R re-selects the same SQL projection, and **all seven fields must still match exactly**. A moved/changed reference yields SKIP. Actual local DOCX digest/ZIP corruption or an explicit API identity/failure disagreement yields FAIL; inconclusive SQL, filesystem or HTTP checks yield SKIP. A PASS means a **bounded observed same-item chain**, not cryptographic proof of atomic cross-system state.

## Known limitations and next acceptance gates

- SQL reads and HTTP/filesystem reads are **sequential observations**, not a serializable, distributed transaction. The latest item can change temporarily then revert, or change just after the second SQL read; other code can also replace database/file content without altering selected text. This probe narrows, but does not eliminate, TOCTOU. It does not validate a trusted SRAF localhost listener/PID or a signed artifact provenance contract.
- It verifies **one selected run item**, not all selected jobs, entire batch, Agent/LLM/Elasticsearch computations or physical isolation. The existing `WORD` row remains NOT_TESTED; `feature_acceptance=NOT_TESTED`, overall INCOMPLETE unless independently found issues.
- Hosted CI uses fake SQL cursors, synthetic DOCX files, and stubbed API status, not live SQL Server parser/permissions or real authenticated Report Job. Actual deployment operator-authorized SQL Server SQL syntax, TLS/SAN, local API owner, filesystem and network isolation remain untested.
