# agent/utils/profiler.py
import os
import time
from contextlib import contextmanager
from typing import Callable, Optional, Dict, Any

# 用環境變數控制要不要輸出 profiling log
DEBUG_PROFILING = os.getenv("DEBUG_PROFILING", "1") == "1"


def _default_logger(msg: str) -> None:
    # 目前先用 print，之後要接 logging.Logger 再改
    print(msg)


@contextmanager
def log_duration(
    label: str,
    logger: Optional[Callable[[str], None]] = None,
    extra: Optional[Dict[str, Any]] = None,
):
    """
    範例：
        with log_duration("[es_search_news][T1] compute_effective_terms"):
            core_terms, ... = compute_effective_terms(raw_query)
    """
    if not DEBUG_PROFILING:
        # 關掉 profiling 時，維持語意但不做任何事
        yield
        return

    logger = logger or _default_logger
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        msg = f"{label} 花費 {dt:.3f}s"
        if extra:
            kv = " ".join(f"{k}={v}" for k, v in extra.items())
            msg = f"{msg} {kv}"
        logger(msg)


def log_total(
    label: str,
    t_start: float,
    logger: Optional[Callable[[str], None]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    範例：
        t_start = time.perf_counter()
        ...
        log_total("[es_search_news][TOTAL]", t_start, extra={"query": raw_query})
    """
    if not DEBUG_PROFILING:
        return

    logger = logger or _default_logger
    dt = time.perf_counter() - t_start
    msg = f"{label} total={dt:.3f}s"
    if extra:
        kv = " ".join(f"{k}={v}" for k, v in extra.items())
        msg = f"{msg} {kv}"
    logger(msg)