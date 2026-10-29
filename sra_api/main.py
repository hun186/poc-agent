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
from sra_api.routers import operator_e2e, requirement_schedules, requirement_tasks
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.security.signed_urls import validate_signing_config
from api.services.auth_support import PRODUCTION_ENVS
from sra_api.middleware.product_preview_body_limit import ProductPreviewBodyLimitMiddleware
from shared.runtime_provenance import requirement_sql_registry_path
from sra_api.startup_diagnostics import startup_phase

@asynccontextmanager
async def lifespan(app: FastAPI):
    with startup_phase("signing_config"):
        validate_signing_config()
    # The API process owns ReportJobWorker and therefore owns/fixes the E2E
    # external plan before any Report Job can be claimed. The operator harness
    # merely asserts this evidence through the authenticated endpoint.
    with startup_phase("external_plan"):
        from agent.external_capabilities import parse_mode
        # Normal service startup validates configuration but does not run
        # expensive LLM/ES acceptance probes or seed the E2E fixture index.
        # An authenticated operator runtime-evidence request prepares the plan.
        parse_mode(os.getenv("REQUIREMENT_E2E_EXTERNAL_MODE"))
    app.state.requirement_import_service = None
    app.state.requirement_schedule_service = None
    app.state.requirement_product_service = None
    pipeline_enabled = os.getenv("REQUIREMENT_PIPELINE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    scheduler_enabled = os.getenv("REQUIREMENT_SCHEDULER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if pipeline_enabled:
        with startup_phase("requirement_pipeline"):
            from data_ingestion.requirements.connections import SqlRegistry
            from data_ingestion.requirements.service import RequirementImportService
            from data_ingestion.requirements.store import RequirementStore
            registry_file = requirement_sql_registry_path(Path.cwd())
            registry = SqlRegistry.load(registry_file)
            requirement_store = RequirementStore(
                registry,
                os.getenv("REQUIREMENT_CONTROL_DB_CONNECTION", "requirement_control"),
                os.getenv("REQUIREMENT_DB_SCHEMA", "sra_requirement"),
                schedule_schema=(
                    os.getenv("REQUIREMENT_SCHEDULE_DB_SCHEMA", "sra_schedule")
                    if scheduler_enabled
                    else None
                ),
            )
            requirement_store.initialize()
            app.state.requirement_import_service = RequirementImportService(requirement_store, registry)
    if scheduler_enabled:
        with startup_phase("schedule_pipeline"):
            from data_ingestion.requirements.connections import SqlRegistry
            from requirement_scheduler.service import ScheduleService
            from requirement_scheduler.store import ScheduleStore
            from sra_api.services.editor_audit import append_audit_event
            registry = SqlRegistry.load(requirement_sql_registry_path(Path.cwd()))
            schedule_store = ScheduleStore(registry, os.getenv("REQUIREMENT_CONTROL_DB_CONNECTION", "requirement_control"), os.getenv("REQUIREMENT_SCHEDULE_DB_SCHEMA", "sra_schedule"), os.getenv("REQUIREMENT_DB_SCHEMA", "sra_requirement"), audit_sink=append_audit_event)
            schedule_store.initialize()
            app.state.requirement_schedule_service = ScheduleService(schedule_store)
            if app.state.requirement_import_service is not None:
                from sra_api.services.requirement_product_service import RequirementProductService
                app.state.requirement_product_service = RequirementProductService(
                    requirement_import_service=app.state.requirement_import_service,
                    schedule_store=schedule_store,
                )
    with startup_phase("report_job_store"):
        store = ReportJobStore(os.getenv("REPORT_JOBS_DB_PATH", ".api_jobs/jobs.sqlite3"), int(os.getenv("REPORT_JOBS_SQLITE_BUSY_TIMEOUT_MS", "5000")))
        reports_root = Path(os.getenv("REPORT_JOBS_REPORTS_ROOT", ".api_jobs/reports"))
        store.initialize()
        store.recover_running()
    with startup_phase("report_job_worker_start"):
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

# Registered first so CORS wraps the limiter's early 413 ASGI response.
# The limiter still executes before multipart form parsing and disk spooling.
app.add_middleware(ProductPreviewBodyLimitMiddleware)

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
app.include_router(requirement_tasks.router)
