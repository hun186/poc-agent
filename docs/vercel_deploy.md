# Vercel Preview Deployment

This project can be deployed to Vercel as a FastAPI preview app for UI review.
The Vercel deployment is intended to run with the mock runtime when the real
Elasticsearch / SQL Server services are not reachable from Vercel.

## Files used by Vercel

- `api/index.py` is the Vercel-routed Python function and reuses `api.main.app`; root `app.py` remains a local/import convenience wrapper.
- The real application source lives under `sra_api/`; top-level `api/` is only a
  compatibility shim so existing `api.*` imports still work while Vercel sees
  only `api/__init__.py` and `api/index.py`, not dozens of `api/**/*.py` files as separate functions.
- `vercel.json` intentionally does not define legacy `builds`, `routes`, or
  `functions`; it only rewrites all traffic to `/api/index.py`, the single
  FastAPI function entrypoint supported by Vercel's Python runtime.
- `requirements.txt` remains the Python dependency source installed by Vercel.

## Bundle size controls

Vercel's default Serverless Function bundle limit is 245 MB. The repository
contains local corpora, generated runtime state, logs, sample files, and
documentation that are useful for on-premise development but are not required by
the preview runtime. `.vercelignore` excludes those local-only directories from
Vercel uploads so the deployed bundle contains the app source and required
static assets instead of the full local data workspace.

`.vercelignore` also excludes legacy conflict-resolution mirrors under
`api/routers/` and `api/static/`. They remain in git only to make GitHub merges
with older base branches non-conflicting; runtime imports prefer `sra_api/`, and
Vercel only needs `api/index.py` plus the small `api/__init__.py` shim.

## Required Vercel environment variables

For a mock-only preview deployment, keep the non-secret defaults in
`vercel.json`. Vercel supports environment variables in this file, so
`SRA_VERCEL_MOCK_MODE=auto` is checked in as a preview-friendly default while
the application still reads Vercel's built-in `VERCEL_ENV` to keep production
safe:

```text
SRA_VERCEL_MOCK_MODE=auto
API_STORE_ENABLED=0
```

Optional but recommended for public preview deployments:

```text
SRA_VERCEL_PREVIEW_LOGIN_SECRET=<long random preview-only secret>
```

Example placeholder in `.env.example`:
`SRA_VERCEL_PREVIEW_LOGIN_SECRET=replace-with-random-preview-secret`. Do not
reuse that placeholder on public deployments; generate a unique value in Vercel
Project Settings.

`auto` means:

1. Production-like environments (`APP_ENV=production`, `ENV=production`,
   `PY_ENV=production`, or `VERCEL_ENV=production`) keep mock runtime and mock
   preview login disabled unless `SRA_VERCEL_MOCK_MODE=force` is set.
2. If Vercel can reach the real Elasticsearch configured by `ES_URL`, the app
   will use the real Elasticsearch.
3. If Vercel is read-only or cannot reach Elasticsearch, the app switches to the
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

## Vercel mock preview login

For Vercel preview deployments running in mock mode, open `/editor` and click
`Vercel mock 閱讀者登入`. The button calls a mock-only endpoint that creates a
process-local preview user in `/tmp` and returns a normal Editor bearer token.
Editor audit events also default to `/tmp` on Vercel so mock login does not
write under the read-only `/var/task/logs` directory. No fixed password is
committed to the repository, and the endpoint returns 404
when mock runtime is disabled, for example with `SRA_VERCEL_MOCK_MODE=never`.
If `SRA_VERCEL_PREVIEW_LOGIN_SECRET` is configured, the UI prompts for that
secret and the backend requires it in `X-SRA-Preview-Login-Secret` before
issuing a token. The endpoint is rate-limited per client host, and tokens issued
by this endpoint are marked as mock-preview tokens.

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
PYTHONPATH=. python -m py_compile app.py api/index.py sra_api/services/vercel_mock_runtime.py agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py
PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_mock_runtime.py -q
```
