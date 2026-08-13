from agent.routing import (
    ROUTER_CURRENT_MAX_CHARS,
    ROUTER_HISTORY_MAX_CHARS,
    build_router_input,
)


def test_router_input_compacts_large_current_payload_and_keeps_both_ends():
    current = "請分析以下資料並產生報告。" + ("資料列,123456\n" * 2000) + "最後要求：輸出繁體中文。"

    result = build_router_input(current)

    payload = result.split("\n", 1)[1]
    assert len(payload) == ROUTER_CURRENT_MAX_CHARS
    assert payload.startswith("請分析以下資料並產生報告。")
    assert payload.endswith("最後要求：輸出繁體中文。")
    assert "中間大量任務資料已省略" in payload


def test_router_input_compacts_history_independently():
    history = "過去指示：延續分析。" + ("歷史資料" * 1000) + "過去結尾"

    result = build_router_input("目前只要改成表格", [history], k=1)

    history_payload = result.split("【過去問題1", 1)[1].split("\n", 1)[1]
    assert len(history_payload) == ROUTER_HISTORY_MAX_CHARS
    assert history_payload.startswith("過去指示：延續分析。")
    assert history_payload.endswith("過去結尾")


def test_router_input_leaves_short_messages_unchanged():
    result = build_router_input("請翻譯這一句", ["上一輪在談翻譯"], k=1)

    assert "【目前問題（務必以此為準）】\n請翻譯這一句" in result
    assert "【過去問題1" in result
    assert "中間大量任務資料已省略" not in result
