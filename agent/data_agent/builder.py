# agent/data_agent/builder.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple, Optional

from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool

from ..tools_es import ESSearchNews, ESTimeline, ESFetchDocById
from ..tools_stats import AggregateMonthQuarter

from .types import ENV
from .prompts import REPORT_DATA_SYSTEM, STYLE_DATA_CODE_SYSTEM

logger = logging.getLogger(__name__)

_SHARED_MODEL: Optional[LiteLLMModel] = None


def normalize_model_id(mid: str) -> str:
    if "/" in (mid or ""):
        return mid
    return f"ollama_chat/{mid}"


def _make_code_agent(tools, model, system_prompt: str) -> CodeAgent:
    common_kwargs = {
        "tools": tools,
        "additional_authorized_imports": ["json"],
    }

    try:
        return CodeAgent(model=model, instructions=system_prompt, **common_kwargs)
    except TypeError as e:
        logger.debug("[data_agent] CodeAgent model+instructions failed: %s", e)

    try:
        return CodeAgent(llm=model, system_prompt=system_prompt, **common_kwargs)
    except TypeError as e:
        logger.debug("[data_agent] CodeAgent llm+system_prompt failed: %s", e)

    try:
        return CodeAgent(model=model, **common_kwargs)
    except TypeError as e:
        logger.debug("[data_agent] CodeAgent model only failed: %s", e)

    try:
        return CodeAgent(llm=model, **common_kwargs)
    except TypeError as e:
        raise RuntimeError(
            "無法用目前 smolagents 版本建立 CodeAgent，請確認 __init__ 參數。"
            f"原始錯誤：{e}"
        )


def build_model() -> LiteLLMModel:
    global _SHARED_MODEL
    if _SHARED_MODEL is not None:
        return _SHARED_MODEL

    effective_model_id = normalize_model_id(ENV.data_agent_model_id)

    extra_kwargs: Dict[str, Any] = {}
    if ENV.tool_choice:
        extra_kwargs["tool_choice"] = ENV.tool_choice

    _SHARED_MODEL = LiteLLMModel(
        model_id=effective_model_id,
        api_base=ENV.model_base_url,
        temperature=ENV.model_temperature,
        extra_generation_kwargs=extra_kwargs or None,
    )
    return _SHARED_MODEL


def _build_mode_assets(mode: str) -> Tuple[List[Any], str]:
    m = (mode or "").strip().lower()

    if m in ("report", "sra_report"):
        tools = [
            ESSearchNews(),
            ESTimeline(),
            ESFetchDocById(),
            AggregateMonthQuarter(),
            PythonInterpreterTool(),
        ]
        return tools, REPORT_DATA_SYSTEM

    if m in ("style", "sra_style"):
        tools = [
            ESSearchNews(),
            ESTimeline(),    # 先保留，若確定不用可再移除
            ESFetchDocById(),
            PythonInterpreterTool(),
        ]
        return tools, STYLE_DATA_CODE_SYSTEM

    raise ValueError(f"未知的 agent mode: {mode}")


def build_agent(mode: str = "report") -> CodeAgent:
    model = build_model()
    tools, system_prompt = _build_mode_assets(mode)
    return _make_code_agent(tools, model, system_prompt=system_prompt)
