# agent/config/query_refiner_settings.py
import os
from dataclasses import dataclass

def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y", "on"))

def _env_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default).strip())
    except Exception:
        return int(default)

def _env_str(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default

@dataclass(frozen=True)
class QueryRefinerConfig:
    enabled: bool
    model_id: str | None
    timeout_sec: float
    use_context: bool
    max_context_chars: int

def load_report_refiner_config() -> QueryRefinerConfig:
    enabled = _env_bool("QUERY_REFINER_REPORT_ENABLED", "0")

    # 專用 > 通用 > None
    model_id = (
        _env_str("QUERY_REFINER_REPORT_MODEL_ID")
        or _env_str("QUERY_REFINER_MODEL_ID")
        or None
    )

    timeout = float(
        _env_int("QUERY_REFINER_REPORT_TIMEOUT", os.getenv("QUERY_REFINER_TIMEOUT", "60"))
    )

    use_context = _env_bool("QUERY_REFINER_REPORT_USE_CONTEXT", "1")
    max_chars = _env_int("QUERY_REFINER_REPORT_MAX_CONTEXT_CHARS", "4000")

    return QueryRefinerConfig(
        enabled=enabled,
        model_id=model_id,
        timeout_sec=timeout,
        use_context=use_context,
        max_context_chars=max_chars,
    )
