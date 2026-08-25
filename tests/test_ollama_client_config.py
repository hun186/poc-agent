from agent.llm_utils import ollama_client
import json


def test_call_llm_forwards_model_override(monkeypatch):
    captured = {}

    class FakeClient:
        def chat(self, messages, *, extra_params, timeout):
            captured["messages"] = messages
            captured["extra_params"] = extra_params
            captured["timeout"] = timeout
            return "ok"

    monkeypatch.setattr(ollama_client, "get_default_client", lambda: FakeClient())

    result = ollama_client.call_llm(
        "hello",
        extra_params={"options": {"temperature": 0}},
        timeout=321,
        model="qwen3.8:latest-16k",
    )

    assert result == "ok"
    assert captured["extra_params"] == {
        "options": {"temperature": 0},
        "model": "qwen3.8:latest-16k",
    }
    assert captured["timeout"] == 321


def test_call_llm_does_not_mutate_extra_params(monkeypatch):
    supplied = {"options": {}}

    class FakeClient:
        def chat(self, messages, *, extra_params, timeout):
            return "ok"

    monkeypatch.setattr(ollama_client, "get_default_client", lambda: FakeClient())

    ollama_client.call_llm("hello", extra_params=supplied, model="other-model")

    assert supplied == {"options": {}}


def test_call_llm_opt_in_adds_time_only_to_system_message_and_logs_it(monkeypatch, caplog):
    captured = {}

    class FakeClient:
        def chat(self, messages, *, extra_params, timeout):
            captured["messages"] = messages
            return "{}"

    monkeypatch.setattr(ollama_client, "get_default_client", lambda: FakeClient())
    monkeypatch.setenv("LLM_CURRENT_TIMEZONE", "Asia/Taipei")
    prompt = json.dumps({"instruction": "只回傳 JSON", "items": [1, 2]}, ensure_ascii=False)

    ollama_client.call_llm(
        prompt,
        system_prompt="只輸出 JSON。",
        include_current_time=True,
        current_time_context_reason="test_relative_date_resolution",
    )

    assert captured["messages"][1] == {"role": "user", "content": prompt}
    system_content = captured["messages"][0]["content"]
    assert system_content.startswith("只輸出 JSON。")
    assert "【系統時間參考】目前時間為" in system_content
    assert "（Asia/Taipei）" in system_content
    assert "current-time system context enabled" in caplog.text
    assert "reason=test_relative_date_resolution" in caplog.text
    assert "timezone=Asia/Taipei" in caplog.text
    assert "output_may_change=true" in caplog.text


def test_call_llm_does_not_add_or_log_current_time_for_strict_json_by_default(monkeypatch, caplog):
    captured = {}

    class FakeClient:
        def chat(self, messages, *, extra_params, timeout):
            captured["messages"] = messages
            return "ok"

    monkeypatch.setattr(ollama_client, "get_default_client", lambda: FakeClient())

    prompt = json.dumps({"published_at": None, "text": "上週發布新聞。"}, ensure_ascii=False)

    ollama_client.call_llm(prompt, system_prompt="無明確日期時輸出 null。")

    assert captured["messages"] == [
        {"role": "system", "content": "無明確日期時輸出 null。"},
        {"role": "user", "content": prompt},
    ]
    assert "current-time system context enabled" not in caplog.text
