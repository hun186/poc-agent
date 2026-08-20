from agent.llm_utils import ollama_client


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
