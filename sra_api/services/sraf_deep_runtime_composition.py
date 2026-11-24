"""Trusted deep runtime composition; no startup or provider IO at import."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
from pathlib import Path
from threading import Lock

from api.services.sraf_deep_startup_config import DeepStartupConfig


@dataclass(repr=False)
class DeepRuntimeComposition:
    policy: object
    runtime: object
    connection: object
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        # Either the Worker thread or startup rollback owns cleanup; both
        # may observe a terminated thread. Never close the SDK twice.
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.connection.close()
            except Exception:
                logging.getLogger("uvicorn.error").error("SRAF deep runtime ES cleanup failed")


def compose_deep_runtime(config: DeepStartupConfig, env: Mapping[str, str],
                         *, project_root: Path) -> DeepRuntimeComposition:
    from api.services.sraf_deep_es_connection import build_deep_es_connection
    from api.services.sraf_deep_scope_policy import DeepScopePolicy
    from api.services.sraf_adaptive_job_runtime import AdaptiveJobRuntime

    policy = DeepScopePolicy(config.policy.grants, config.policy.max_active_jobs)
    models = config.models
    connection = build_deep_es_connection(env, project_root=project_root)
    try:
        runtime = AdaptiveJobRuntime(
            es_client_factory=connection.get_client,
            planner_call=models.plan,
            semantic_assessor=models.assess,
            check_owner_index=policy.check_owner_index,
            check_question_branches=policy.check_question_branches,
            report_call=models.report,
            report_model_id=models.report_model,
        )
        return DeepRuntimeComposition(policy, runtime, connection)
    except BaseException:
        try:
            connection.close()
        except Exception:
            logging.getLogger("uvicorn.error").error("SRAF deep runtime ES cleanup failed")
        raise
