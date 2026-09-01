# Report API

## Choose a mode

Use `POST /v1/report/word` for short/medium one-off work where the client can wait. It retains `ChatPayload` (`model`, `messages`, `stream`) and returns DOCX plus tracking headers. `GET /v1/export/word` remains the independent, snapshot-based compatibility download.

Use `POST /v1/report/jobs` for long work requiring persisted status and polling:

```bash
curl -X POST http://localhost:9002/v1/report/jobs \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: daily-001' \
  -d '{"prompt":"請產生報告","filename":"daily.docx","session_id":"daily-session","model":"SRA-Structured Retrieval Agent","options":{},"metadata":{"task_id":"001"}}'
curl http://localhost:9002/v1/report/jobs/rpt_ID
curl -OJ http://localhost:9002/v1/report/jobs/rpt_ID/word
```

`prompt` is required. `filename` and `session_id` are optional; generated sessions use `report-job-<uuid>`. The model defaults to `SRA-Structured Retrieval Agent`. `options` currently accepts no keys. `metadata` is persisted bookkeeping and does not change execution. Unknown fields are rejected.

Create returns `202` with `job_id`, `queued` status, `status_url`, and `download_url`. Statuses are `queued`, `running`, `completed`, `failed`, and `interrupted`. Download returns `404` for an unknown job, `409` for every non-completed state, and `500` if a completed row lacks a valid readable DOCX.

The optional idempotency key returns the existing job for the same normalized request, regardless of its state; reusing it with different content returns `409`.

```python
import time, requests
r = requests.post("http://localhost:9002/v1/report/jobs", json={"prompt": "請產生報告"})
r.raise_for_status(); job = r.json()
while True:
    state = requests.get("http://localhost:9002" + job["status_url"]).json()
    if state["status"] in {"completed", "failed", "interrupted"}: break
    time.sleep(2)
if state["status"] == "completed":
    content = requests.get("http://localhost:9002" + job["download_url"]).content
    open("report.docx", "wb").write(content)
```
