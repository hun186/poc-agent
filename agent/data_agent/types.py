# agent/data_agent/types.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DataAgentEnv:
    model_id: str
    model_base_url: str
    model_temperature: float
    data_agent_model_id: str
    tool_choice: Optional[str]

    @staticmethod
    def from_env() -> "DataAgentEnv":
        model_id = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
        model_base_url = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
        model_temperature = float(os.getenv("MODEL_TEMPERATURE", "0") or "0")

        # 資料整備代理人專用 model ID（優先使用 DATA_AGENT_MODEL_ID）
        data_agent_model_id = os.getenv("DATA_AGENT_MODEL_ID") or model_id

        # 可選：DATA_AGENT_TOOL_CHOICE=none/auto/required（依你的 LiteLLM/模型支援）
        tool_choice = os.getenv("DATA_AGENT_TOOL_CHOICE")
        if tool_choice is not None:
            tool_choice = tool_choice.strip() or None

        return DataAgentEnv(
            model_id=model_id,
            model_base_url=model_base_url,
            model_temperature=model_temperature,
            data_agent_model_id=data_agent_model_id,
            tool_choice=tool_choice,
        )


ENV = DataAgentEnv.from_env()
