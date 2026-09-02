# api/main.py
# cd D:\shared\TopicClassification\poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 9002
# cd /mntCZJ/TopicClassification/poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 9002
# http://192.168.0.228:9002/v1
# http://192.168.0.133:9002/v1

#cd D:\shared\TopicClassification\poc-agent&&python -m api.run_api --public --ssl --port 9002
#cd /mntCZJ/TopicClassification/poc-agent&&python -m api.run_api --public --port 9002

from api.core.proctitle import init_proctitle

# 啟動時先設定 process title
init_proctitle(app_name="SRA-API")

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI  # , HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from api.routers import chat, docs, export, editor, excel_to_sql, report_jobs, service_keys
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.security.signed_urls import validate_signing_config

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_signing_config()
    store = ReportJobStore(os.getenv("REPORT_JOBS_DB_PATH", ".api_jobs/jobs.sqlite3"), int(os.getenv("REPORT_JOBS_SQLITE_BUSY_TIMEOUT_MS", "5000")))
    reports_root = Path(os.getenv("REPORT_JOBS_REPORTS_ROOT", ".api_jobs/reports"))
    store.initialize()
    store.recover_running()
    worker = ReportJobWorker(store, reports_root)
    app.state.report_job_store = store
    app.state.report_jobs_reports_root = reports_root
    app.state.report_job_worker = worker
    worker.start()
    try: yield
    finally: worker.stop()

app = FastAPI(
    title="SRA-Structured Retrieval Agent (OpenAI-compatible)",
    version="1.0.0",
    lifespan=lifespan,
    redoc_url=None,
)

cors_origins = [origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
wildcard = not cors_origins and (os.getenv("APP_ENV") or "").lower() not in {"prod", "production"}
app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or (["*"] if wildcard else []),
        allow_credentials=not wildcard,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-OpenWebUI-Chat-Id", "X-Conversation-Id", "X-Session-Id"],
    )


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/editor")


app.include_router(chat.router)
app.include_router(docs.router)
app.include_router(export.router)
app.include_router(report_jobs.router)
app.include_router(service_keys.router)
app.include_router(editor.router)
app.include_router(excel_to_sql.router)
