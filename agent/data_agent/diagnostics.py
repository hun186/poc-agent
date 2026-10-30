"""Optional non-mutating DataAgent model.generate timing observation.

Only existing production LiteLLMModel instances are instrumented.  No provider
request is emitted here; callbacks transparently preserve args, result and
exceptions.  A synthetic E2E semantic model must never be instrumented.
"""
from __future__ import annotations

from functools import wraps
import logging
import math
import time
from typing import Any

import requests

from agent.llm_utils.ollama_client import _llm_failure_category

logger = logging.getLogger(__name__)

# Never emit exception text, prompt, response, model IDs, endpoints or keys.
_LITELLM_ERROR_CATEGORIES = {
    "Timeout": "provider_timeout",
    "APITimeoutError": "provider_timeout",
    "RateLimitError": "provider_rate_limited",
    "ServiceUnavailableError": "provider_unavailable",
    "APIConnectionError": "provider_connection_error",
    "InternalServerError": "provider_error",
    "APIError": "provider_error",
    "BadRequestError": "provider_error",
    "AuthenticationError": "provider_error",
    "PermissionDeniedError": "provider_error",
}


def _data_agent_error_category(exc: Exception) -> str:
    """Categorize actual exception objects, not sensitive message text."""
    pending: list[BaseException] = [exc]
    visited: set[int] = set()
    while pending and len(visited) < 12:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, requests.exceptions.RequestException):
            return _llm_failure_category(current)
        cls = type(current)
        if cls.__module__.startswith(("litellm.", "litellm_exceptions.")):
            category = _LITELLM_ERROR_CATEGORIES.get(cls.__name__)
            if category is not None:
                return category
        for child in (current.__cause__, current.__context__, *current.args[:4]):
            if isinstance(child, BaseException) and id(child) not in visited:
                pending.append(child)
    return "provider_error"


def observe_data_agent_model(model: Any) -> Any:
    """Wrap *only* the instance's generate method; retain its concrete type.

    If an incompatible future smolagents version forbids method wrapping,
    production model creation must still work: report the instrumentation gap,
    never mark its calls as observed.
    """
    generate = getattr(model, "generate", None)
    if not callable(generate):
        logger.warning(
            "[llm_call] stage=data_agent outcome=not_observed category=generate_unavailable"
        )
        return model
    if getattr(generate, "_sraf_data_agent_observed", False):
        return model

    @wraps(generate)
    def observed_generate(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = generate(*args, **kwargs)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            if not math.isfinite(elapsed):
                elapsed = 0.0
            logger.warning(
                "[llm_call] stage=data_agent outcome=error category=%s "
                "elapsed_sec=%.3f requests_timeout_sec=unknown",
                _data_agent_error_category(exc), max(0.0, elapsed),
            )
            raise
        elapsed = time.perf_counter() - started
        if not math.isfinite(elapsed):
            elapsed = 0.0
        (logger.warning if elapsed >= 30 else logger.info)(
            "[llm_call] stage=data_agent outcome=success category=none "
            "elapsed_sec=%.3f requests_timeout_sec=unknown",
            max(0.0, elapsed),
        )
        return result

    observed_generate._sraf_data_agent_observed = True
    try:
        model.generate = observed_generate
    except (AttributeError, TypeError):
        logger.warning(
            "[llm_call] stage=data_agent outcome=not_observed category=generate_readonly"
        )
    return model
