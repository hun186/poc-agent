import agent.agent as agent_module


def test_pure_llm_uses_its_own_timeout(monkeypatch):
    received = {}

    monkeypatch.setattr(
        agent_module,
        "route_task_mode",
        lambda *args, **kwargs: {"mode": "PURE_LLM", "topic": "none", "reason": "test"},
    )

    def fake_call_llm(prompt, **kwargs):
        received["prompt"] = prompt
        received["timeout"] = kwargs["timeout"]
        received["include_current_time"] = kwargs["include_current_time"]
        received["current_time_context_reason"] = kwargs["current_time_context_reason"]
        received["stage"] = kwargs["stage"]
        return "完成"

    monkeypatch.setattr(agent_module, "call_llm", fake_call_llm)
    monkeypatch.setattr(agent_module, "PURE_LLM_TIMEOUT", 900.0)

    result = agent_module.answer_with_routing("很長的直接分析任務")

    assert result["answer"] == "完成"
    assert received == {
        "prompt": "很長的直接分析任務",
        "timeout": 900.0,
        "include_current_time": True,
        "current_time_context_reason": "pure_llm_relative_date_resolution",
        "stage": "pure_llm",
    }


def test_positive_env_float_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("TEST_TIMEOUT", "invalid")
    assert agent_module._positive_env_float("TEST_TIMEOUT", 180.0) == 180.0

    monkeypatch.setenv("TEST_TIMEOUT", "0")
    assert agent_module._positive_env_float("TEST_TIMEOUT", 180.0) == 180.0

    monkeypatch.setenv("TEST_TIMEOUT", "900")
    assert agent_module._positive_env_float("TEST_TIMEOUT", 180.0) == 900.0
