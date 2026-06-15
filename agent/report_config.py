# agent/report_config.py
import os

REPORT_MODEL_ID = (
    os.getenv("REPORT_MODEL_ID")   # 有指定就用這個
    or os.getenv("MODEL_ID")       # 沒有就沿用主 MODEL_ID
    or "gpt-oss:120b-32k"          # 再不然給一個預設
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        print(f"[report] invalid {name}={raw!r}; fallback to {default}")
        return default
    if value <= 0:
        print(f"[report] invalid {name}={raw!r}; fallback to {default}")
        return default
    return value


REPORT_LLM_TIMEOUT = _env_float(
    "REPORT_LLM_TIMEOUT",
    _env_float("REPORT_TIMEOUT", 300.0),
)

