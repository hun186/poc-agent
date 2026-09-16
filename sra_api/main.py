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

from config.bootstrap import bootstrap_env

# Security singletons and router globals read environment at import time.  Load
# the project environment before importing any of them.
bootstrap_env()

from fastapi import FastAPI  # , HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from api.routers import chat, docs, export, editor, excel_to_sql, report_jobs, service_keys
from api.routers import requirements
from sra_api.routers import operator_e2e, requirement_schedules
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.security.signed_urls import validate_signing_config
from api.services.auth_support import PRODUCTION_ENVS

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_signing_config()
    app.state.requirement_import_service = None
    app.state.requirement_schedule_service = None
    if os.getenv("REQUIREMENT_PIPELINE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        from data_ingestion.requirements.connections import SqlRegistry
        from data_ingestion.requirements.service import RequirementImportService
        from data_ingestion.requirements.store import RequirementStore
        registry_file = os.getenv("REQUIREMENT_SQL_REGISTRY_FILE", "config/requirements/sql_registry.json")
        registry = SqlRegistry.load(registry_file)
        requirement_store = RequirementStore(registry, os.getenv("REQUIREMENT_CONTROL_DB_CONNECTION", "requirement_control"), os.getenv("REQUIREMENT_DB_SCHEMA", "sra_requirement"))
        requirement_store.initialize()
        app.state.requirement_import_service = RequirementImportService(requirement_store, registry)
    if os.getenv("REQUIREMENT_SCHEDULER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        from data_ingestion.requirements.connections import SqlRegistry
        from requirement_scheduler.service import ScheduleService
        from requirement_scheduler.store import ScheduleStore
        from sra_api.services.editor_audit import append_audit_event
        registry = SqlRegistry.load(os.getenv("REQUIREMENT_SQL_REGISTRY_FILE", "config/requirements/sql_registry.json"))
        schedule_store = ScheduleStore(registry, os.getenv("REQUIREMENT_CONTROL_DB_CONNECTION", "requirement_control"), os.getenv("REQUIREMENT_SCHEDULE_DB_SCHEMA", "sra_schedule"), os.getenv("REQUIREMENT_DB_SCHEMA", "sra_requirement"), audit_sink=append_audit_event)
        schedule_store.initialize()
        app.state.requirement_schedule_service = ScheduleService(schedule_store)
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
wildcard = not cors_origins and (os.getenv("APP_ENV") or "").lower() not in PRODUCTION_ENVS
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
app.include_router(requirements.router)
app.include_router(requirement_schedules.router)
app.include_router(operator_e2e.router)
