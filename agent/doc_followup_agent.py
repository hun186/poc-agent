# agent/doc_followup_agent.py
from typing import Any, Dict, List
import json

from .llm_utils.ollama_client import call_llm
from .tools_es import ESFetchDocById


# === 單一工具實例 ===
_fetch_doc_tool = ESFetchDocById()


def fetch_docs_by_uuid(uuids: List[str], index_hint: str | None = None) -> List[Dict[str, Any]]:
    """
    根據 UUID 清單利用 ESFetchDocById 拉全文。

    回傳格式：
    {
        "index": 1,                 # 1-based，用來對應「第一篇、第二篇」
        "uuid": "...",
        "title": "...",
        "date": "YYYY-MM-DD 或 None",
        "subject": "...",
        "full_text": "原文全文"
    }
    """
    docs: List[Dict[str, Any]] = []

    for idx, u in enumerate(uuids, start=1):
        print(f"[doc_followup] try fetch uuid={u!r}, index_hint={index_hint!r}")
        try:
            doc = _fetch_doc_tool.forward(uuid=u, index_hint=index_hint)
        except Exception as e:
            print(f"[doc_followup] fetch error for {u}: {e}")
            continue

        if not doc:
            print(f"[doc_followup] empty doc for {u}")
            continue

        src = doc.get("source") or {}
        full_text = doc.get("full_text") or ""
        if not full_text.strip():
            print(f"[doc_followup] no full_text for {u}")
            continue

        # 嘗試自動抓標題
        title = (
            src.get("article_title")
            or src.get("title")
            or src.get("rawInfo", {}).get("title")
            or None
        )

        # 嘗試自動抓日期
        date = (
            src.get("article_date_iso")
            or src.get("date_iso")
            or src.get("rawInfo", {}).get("date")
            or None
        )

        # 嘗試 subject
        subject = (
            src.get("subject")
            or src.get("rawInfo", {}).get("subject")
            or None
        )

        full_text = doc.get("full_text") or ""
        if not full_text.strip():
            continue

        docs.append(
            {
                "index": idx,
                "uuid": u,
                "title": title,
                "date": date,
                "subject": subject,
                "full_text": full_text,
            }
        )
    print("[doc_followup] final docs count =", len(docs))
    return docs


DOC_FOLLOWUP_SYSTEM_PROMPT = """
你是一個『文件後續處理助手』。

所有可用資訊都來自 docs 陣列，不能查新的資料庫。

你可以做的任務包含但不限於：
- 把指定篇章翻譯成英文（例如：把第五篇翻成英文）
- 給我第一篇的全文
- 幫我逐篇摘要
- 比較第一篇與第二篇差異
- 基於這些文件做新的說明

輸入 JSON 格式：
{
  "instruction": "使用者目前這一輪的指令",
  "docs": [
    {
      "index": 1,
      "uuid": "...",
      "title": "...",
      "date": "...",
      "subject": "...",
      "full_text": "......"
    }
  ]
}

規則：
1. 所有內容都只能來自 docs[i].full_text，不可新增外部事實。
2. 使用者說「第一篇、第二篇」要對應 index。
3. 若語言未指定，預設輸出繁體中文。
4. 若 docs 為空，必須回應「目前沒有可用的文件」。
"""


def ask_with_doc_followup(instruction: str, uuids: List[str], index_hint: str | None = None) -> Dict[str, Any]:
    """
    通用文件後續代理人入口。
    """
    docs = fetch_docs_by_uuid(uuids, index_hint=index_hint)

    if not docs:
        return {
            "answer": "目前沒有可用的參考文件，因此無法進行這一輪的指令。",
            "citations": [],
            "reasoning": "沒有文件可使用",
            "used_uuids": uuids,
        }

    payload = {
        "instruction": instruction,
        "docs": docs,
    }

    user_prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    answer = call_llm(
        user_prompt,
        system_prompt=DOC_FOLLOWUP_SYSTEM_PROMPT,
        extra_params={"options": {}},
        timeout=180.0,
    )

    return {
        "answer": answer,
        "citations": [],
        "reasoning": "僅依據先前取得的文件全文進行後續任務。",
        "used_uuids": uuids,
        "doc_count": len(docs),
    }
