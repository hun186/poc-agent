# Vercel Preview Deployment

This project can be deployed to Vercel as a FastAPI preview app for UI review.
The Vercel deployment is intended to run with the mock runtime when the real
Elasticsearch / SQL Server services are not reachable from Vercel.

## Files used by Vercel

- Root `app.py` exports the FastAPI `app` object and reuses `api.main.app`.
- `vercel.json` uses an explicit single `@vercel/python` build for `app.py` and
  routes all requests to that file. This avoids Vercel treating every Python
  module under this repository's existing `api/` application package as a
  separate Hobby-plan Serverless Function.
- `requirements.txt` remains the Python dependency source installed by Vercel.

## Bundle size controls

Vercel's default Serverless Function bundle limit is 245 MB. The repository
contains local corpora, generated runtime state, logs, sample files, and
documentation that are useful for on-premise development but are not required by
the preview runtime. `.vercelignore` excludes those local-only directories from
Vercel uploads so the deployed bundle contains the app source and required
static assets instead of the full local data workspace.

## Required Vercel environment variables

For a mock-only preview deployment, set these in Vercel Project Settings or keep
the non-secret defaults from `vercel.json`:

```text
SRA_VERCEL_MOCK_MODE=auto
API_STORE_ENABLED=0
```

`auto` means:

1. If Vercel can reach the real Elasticsearch configured by `ES_URL`, the app
   will use the real Elasticsearch.
2. If Vercel is read-only or cannot reach Elasticsearch, the app switches to the
   in-memory mock Elasticsearch and mock Excel→SQL dataset.

For a real-data deployment, additionally configure the normal service variables
from `.env.example`, especially:

```text
ES_URL=...
ES_USERNAME=...
ES_PASSWORD=...
ES_INDEX=...
SRA_AUTH_SECRET=<at least 32 bytes if APP_ENV/ENV/PY_ENV is production>
```

Do not commit real secrets to the repository.

## Mock runtime behavior on Vercel

When mock mode is active:

- Editor search/index APIs return `mock_mode: true` and use
  `vercel_mock_vessel_activities`.
- Excel upload records are stored in process memory instead of the filesystem.
- Excel preview / confirm responses are mock payloads marked with
  `mock_mode: true`.
- Excel→SQL dashboard and delete-row APIs use mock SQL audit data and do not
  connect to SQL Server.

Because Vercel functions are serverless, process memory is not durable across
cold starts or instances. The mock dataset is for review only.

## Local verification before pushing

```bash
PYTHONPATH=. python -m py_compile app.py api/services/vercel_mock_runtime.py agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py
PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_mock_runtime.py -q
```
