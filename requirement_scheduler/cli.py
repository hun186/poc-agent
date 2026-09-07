from __future__ import annotations
import argparse
import os
from pathlib import Path

from data_ingestion.requirements.connections import SqlRegistry
from requirement_scheduler.config import RequirementHandoffConfig
from requirement_scheduler.coordinator import RequirementHandoffCoordinator
from requirement_scheduler.handoff import RequirementHandoffService
from requirement_scheduler.legacy_report_job_gateway import LegacyReportJobGateway
from requirement_scheduler.reconciliation import RequirementReconciler
from requirement_scheduler.store import ScheduleStore

def build_coordinator_from_env() -> RequirementHandoffCoordinator:
    """Construct the external worker exclusively from server-owned environment."""
    registry=SqlRegistry.load(os.getenv("REQUIREMENT_SQL_REGISTRY_FILE","config/requirements/sql_registry.json"))
    credential_env=os.getenv("REQUIREMENT_HANDOFF_CREDENTIAL_ENV","REQUIREMENT_HANDOFF_CREDENTIAL")
    def resolve(_: str) -> str: return os.getenv(credential_env,"")
    config=RequirementHandoffConfig(
        api_base_url=os.environ["REQUIREMENT_HANDOFF_API_BASE_URL"],
        logical_principal=os.environ["REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL"],
        credential_provider=resolve,
        output_root=Path(os.environ["REQUIREMENT_HANDOFF_OUTPUT_ROOT"]),
        connect_timeout=float(os.getenv("REQUIREMENT_HANDOFF_CONNECT_TIMEOUT","5")),
        read_timeout=float(os.getenv("REQUIREMENT_HANDOFF_READ_TIMEOUT","60")),
        poll_interval=float(os.getenv("REQUIREMENT_HANDOFF_POLL_INTERVAL","2")),
        heartbeat_interval=float(os.getenv("REQUIREMENT_HANDOFF_HEARTBEAT_INTERVAL","10")),
        lease_duration=float(os.getenv("REQUIREMENT_HANDOFF_LEASE_DURATION","45")),
        request_retries=int(os.getenv("REQUIREMENT_HANDOFF_REQUEST_RETRIES","3")),
        max_backoff=float(os.getenv("REQUIREMENT_HANDOFF_MAX_BACKOFF","5")),
        batch_size=int(os.getenv("REQUIREMENT_HANDOFF_BATCH_SIZE","20")),
        allow_insecure_localhost=os.getenv("REQUIREMENT_HANDOFF_ALLOW_INSECURE_LOCALHOST","false").lower() in {"1","true","yes"},
    )
    store=ScheduleStore(registry,os.getenv("REQUIREMENT_CONTROL_DB_CONNECTION","requirement_control"),os.getenv("REQUIREMENT_SCHEDULE_DB_SCHEMA","sra_schedule"),os.getenv("REQUIREMENT_DB_SCHEMA","sra_requirement"))
    gateway=LegacyReportJobGateway(config)
    service=RequirementHandoffService(store,gateway,config.output_root)
    return RequirementHandoffCoordinator(store,RequirementReconciler(store,service),service,config,owner_id=os.getenv("REQUIREMENT_HANDOFF_OWNER_ID") or f"handoff-{os.getpid()}")

def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="python -m requirement_scheduler")
    parser.add_argument("command",choices=("handoff-worker",))
    return parser

def main(argv=None, *, coordinator_factory=None) -> int:
    args=build_parser().parse_args(argv)
    if args.command == "handoff-worker":
        coordinator_factory = coordinator_factory or build_coordinator_from_env
        import threading
        stop=threading.Event()
        try: coordinator_factory().run(stop)
        except KeyboardInterrupt: stop.set()
        return 0
    return 2
