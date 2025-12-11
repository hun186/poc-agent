# api/services/memory.py
import json
from typing import Dict
from api.core.settings import json_llm

# ===== 通用多輪記憶（緊湊 JSON 狀態）=====
_memory: dict[str, dict] = {}   # 會話 -> 濃縮記憶(JSON)

def render_memory_text(mem: dict | None) -> str:
    """把 JSON 記憶轉成可提示的短文字塊。"""
    if not mem:
        return ""
    parts = []
    if mem.get("topic"): parts.append(f"- 主題：{mem['topic']}")
    if mem.get("time_range"): parts.append(f"- 時間範圍：{mem['time_range']}")
    if mem.get("subtopics"): parts.append(f"- 子題：{', '.join([str(x) for x in mem['subtopics']][:6])}")
    if mem.get("entities"): parts.append(f"- 重要實體：{', '.join([str(x) for x in mem['entities']][:10])}")
    if mem.get("constraints"): parts.append(f"- 既定限制：{'; '.join([str(x) for x in mem['constraints']][:6])}")
    if mem.get("open_questions"): parts.append(f"- 未決問題：{'; '.join([str(x) for x in mem['open_questions']][:5])}")
    return "\n".join(parts).strip()

MEMORY_SYSTEM = "你是會話記憶壓縮器。請把對話濃縮成能幫助後續追問的一小段 JSON 狀態，保持簡潔、去重。"
def update_memory(session_id: str, history_tail_text: str, last_out: dict | None):
    """用最近幾輪對話與上一輪輸出，產生/更新通用記憶(JSON)。"""
    prev = _memory.get(session_id) or {}
    last_answer = ""
    if isinstance(last_out, dict):
        last_answer = str(last_out.get("answer") or "")[:2000]
    user = (
        "請根據【既有記憶】與【最新對話片段】及【上一輪答案節選】，輸出緊湊 JSON：\n"
        '{ "topic": "", "time_range": "", "subtopics": [], "entities": [], "constraints": [], "open_questions": [] }\n\n'
        f"【既有記憶】\n{json.dumps(prev, ensure_ascii=False)}\n\n"
        f"【最新對話片段】\n{history_tail_text}\n\n"
        f"【上一輪答案節選】\n{last_answer}\n"
    )
    try:
        mem = json_llm.generate_json(
            MEMORY_SYSTEM,
            user,
            schema_hint='{"topic":"","time_range":"","subtopics":[],"entities":[],"constraints":[],"open_questions":[]}',
            num_ctx=32768
        )
        if isinstance(mem, dict):
            _memory[session_id] = mem
    except Exception:
        # 記憶更新失敗不影響主流程
        pass
    
def get_memory():
    return _memory