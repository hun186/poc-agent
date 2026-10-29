# agent/utils/evidence_pack.py
from __future__ import annotations
from typing import Any, Dict, List, Set

import json
import os
import re

ALL_EV_FIELDS: Set[str] = {
    "ref_no", "id", "d", "title", "s", "note",
    "weak", "scope", "group_hits",
}

FIELD_DESC: Dict[str, str] = {
    "ref_no": "必填引用編號（來源N），永遠保留",
    "id": "文件識別/uuid，用於追溯來源文件",
    "d": "片段日期，用於時間線/排序",
    "title": "片段/文章標題，用於描述引用來源",
    "s": "subject/主題標籤，用於分群或彙整主題",
    "note": "片段文字（事實來源），永遠保留",
    "weak": "是否弱證據，用於可信度/篩選說明",
    "scope": "命中範圍/匹配類型，用於解釋為何命中",
    "group_hits": "群組命中細節，用於除錯/解釋命中原因",
}

# 固定欄位輸出順序（很重要：token/快取穩定）
FIELD_ORDER: List[str] = ["ref_no", "note", "d", "title", "s", "id", "weak", "scope", "group_hits"]

DEFAULT_FIELDS: Set[str] = {"ref_no", "note", "d", "title"}  # 你 prompt 也寫 note 必填，這裡就對齊


def guess_report_need_fields(q: str) -> Set[str]:
    """
    規則式欄位策略：只會「加欄位」，不會把必要欄位拿掉。
    """
    qn = (q or "").strip().lower()
    fields = set(DEFAULT_FIELDS)

    # 追溯文件/來源定位（列出哪些文章/uuid/id）
    if any(k in qn for k in ["uuid", "來源文件", "出處", "哪幾篇", "哪些文件", "文章", "doc", "document", "id"]):
        fields |= {"id", "s"}

    # 需要分群/分主題/依 subject 統整
    if any(k in qn for k in ["分群", "分類", "主題", "類別", "subject", "依單位", "依來源", "依主題"]):
        fields |= {"s"}

    # 需要解釋為何命中/為何弱證據/篩選條件
    if any(k in qn for k in ["為什麼", "可信", "信度", "強弱", "弱證據", "篩選", "過濾", "命中", "scope", "group_hits"]):
        fields |= {"weak", "scope", "group_hits"}

    return fields

LLM_FIELD_SELECTOR_SYSTEM = """你是一個欄位選擇器。
任務：依據使用者問題 q，從候選欄位中選出「報告真正需要」的欄位，以節省 token。

規則：
- 一律回傳 JSON，格式必須是：{"fields":["ref_no","note",...]}
- fields 只能選自 candidates 內的欄位
- 必須包含 ref_no 與 note
- 若問題涉及時間線/年月日，請包含 d
- 若問題要求列出來源/哪幾篇/uuid/出處，請包含 id（必要時也包含 title/s）
- 若問題涉及分群/主題/依來源彙整，請包含 s
- 若問題要求解釋命中/強弱/可信度/為何被抓到，請包含 weak/scope/group_hits（需要哪個就選哪個）
- 盡量少選欄位（除 ref_no/note 必需外，能不選就不選）
"""

def _safe_parse_fields_json(text: str) -> List[str] | None:
    if not isinstance(text, str):
        return None
    s = text.strip()

    # 嘗試抓 JSON 物件
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if m:
        s = m.group(0)

    try:
        obj = json.loads(s)
        fields = obj.get("fields")
        if not isinstance(fields, list):
            return None
        out = []
        for f in fields:
            if isinstance(f, str):
                out.append(f.strip())
        return out or None
    except Exception:
        return None


def llm_select_fields(
    q: str,
    call_llm_fn,
    *,
    model: str | None = None,
    timeout: float = 60.0,
    max_fields: int = 10,
) -> Set[str] | None:
    """
    只送 q + 欄位清單/說明，不送 ev，因此 token 成本很低。
    回傳 None 表示失敗（讓上層 fallback）。
    """
    candidates = sorted(list(ALL_EV_FIELDS))
    user_payload = {
        "q": (q or "").strip(),
        "candidates": [
            {"name": f, "desc": FIELD_DESC.get(f, "")}
            for f in candidates
        ],
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))

    ans = call_llm_fn(
        user_prompt,
        system_prompt=LLM_FIELD_SELECTOR_SYSTEM,
        extra_params={"options": {"temperature": 0}},
        timeout=timeout,
        model=model,
    )

    fields_list = _safe_parse_fields_json(ans)
    if not fields_list:
        return None

    allow = set(fields_list) & ALL_EV_FIELDS

    # ref_no/note 保底
    allow |= {"ref_no", "note"}

    # 控制最大欄位數：保留最重要的優先順序
    # （避免 LLM 一口氣全選）
    priority = ["ref_no", "note", "d", "title", "s", "id", "weak", "scope", "group_hits"]
    if len(allow) > max_fields:
        trimmed = []
        for f in priority:
            if f in allow:
                trimmed.append(f)
            if len(trimmed) >= max_fields:
                break
        allow = set(trimmed)

    return allow


'''
def _fill_value_for_llm(v: Any) -> Any:
    """
    避免 LLM 看到 None 或空字串造成格式雜訊。
    你原本表格規則也不允許空值，這裡先做一致化。
    """
    if v is None:
        return "未知"
    if isinstance(v, str) and v.strip() == "":
        return "未知"
    return v


def filter_ev_fields(ev: List[Dict[str, Any]], allow_fields: Set[str]) -> List[Dict[str, Any]]:
    allow = (set(allow_fields) & ALL_EV_FIELDS) | {"ref_no"}  # ref_no 保底
    out: List[Dict[str, Any]] = []
    for row in ev or []:
        slim = {k: _fill_value_for_llm(row.get(k)) for k in allow}
        out.append(slim)
    return out
'''
def filter_ev_fields(ev: List[Dict[str, Any]], allow_fields: Set[str]) -> List[Dict[str, Any]]:
    # ref_no + note 永遠保底（不然整個引用規則會崩）
    allow = (set(allow_fields) & ALL_EV_FIELDS) | {"ref_no", "note"}

    # 用固定順序輸出 key（避免 set 順序不穩）
    allow_ordered = [k for k in FIELD_ORDER if k in allow]

    out: List[Dict[str, Any]] = []
    for row in (ev or []):
        slim: Dict[str, Any] = {}

        # ref_no / note 強制要有（就算空，也要保留）
        slim["ref_no"] = row.get("ref_no")
        slim["note"] = row.get("note") or row.get("text") or ""

        # 其他欄位：有值才輸出（token 立刻省一截）
        for k in allow_ordered:
            if k in ("ref_no", "note"):
                continue
            v = row.get(k)
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            slim[k] = v

        out.append(slim)
    return out

'''
def pack_ev_for_llm(ev_compact: List[Dict[str, Any]], q: str) -> Dict[str, Any]:
    allow = guess_report_need_fields(q)
    ev_slim = filter_ev_fields(ev_compact, allow)
    return {
        "ev_slim": ev_slim,
        "meta": {
            "allow_fields": sorted(allow),
            "fields_count": len(allow),
        }
    }
'''

def _selector_failure_code(exc: Exception) -> str:
    """Stable, redacted error code; follow chained Ollama transport failures."""
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, TimeoutError) or type(current).__name__ in {
            "ReadTimeout", "ConnectTimeout", "Timeout", "APITimeoutError",
        }:
            return "timeout"
        if isinstance(current, ConnectionError) or type(current).__name__ in {
            "APIConnectionError",
        }:
            return "transport_unavailable"
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "llm_runtime_failure" if isinstance(exc, RuntimeError) else "selector_error"


def pack_ev_for_llm(
    ev_compact: List[Dict[str, Any]],
    q: str,
    *,
    mode: str | None = None,          # "rules" | "llm" | "hybrid"
    call_llm_fn=None,                 # 由外部傳入（避免 utils 直接依賴 ollama_client）
    llm_model: str | None = None,
    llm_timeout: float = 60.0,
    llm_max_fields: int = 10,
) -> Dict[str, Any]:
    """
    mode:
      - rules: 使用 guess_report_need_fields
      - llm: 使用 llm_select_fields（失敗 fallback rules）
      - hybrid: 以 rules 為底，LLM 只負責「加欄位」（不會拿掉 DEFAULT_FIELDS）
    """
    mode = (mode or os.getenv("REPORT_EV_FIELD_SELECTOR_MODE", "hybrid")).strip().lower()

    allow_rules = guess_report_need_fields(q)

    allow = set(allow_rules)
    llm_used = False
    llm_error = None
    llm_attempted = False

    if mode in ("llm", "hybrid"):
        if call_llm_fn is None:
            llm_error = "selector_not_configured"
        else:
            try:
                llm_attempted = True
                allow_llm = llm_select_fields(
                    q, call_llm_fn, model=llm_model,
                    timeout=llm_timeout, max_fields=llm_max_fields,
                )
                if allow_llm:
                    llm_used = True
                    if mode == "llm":
                        allow = allow_llm
                    else:  # hybrid only adds to rules baseline
                        allow = allow_rules | allow_llm
                else:
                    llm_error = "invalid_response"
            except Exception as e:
                # Never expose raw transport exception URLs/tokens to UI/trace.
                llm_error = _selector_failure_code(e)

    fallback_used = mode in ("llm", "hybrid") and not llm_used
    ev_slim = filter_ev_fields(ev_compact, allow)

    return {
        "ev_slim": ev_slim,
        "meta": {
            "mode": mode,
            "llm_used": llm_used,
            "llm_attempted": llm_attempted,
            "llm_error": llm_error,
            "fallback_used": fallback_used,
            "fallback_strategy": "rules" if fallback_used else None,
            "allow_fields": sorted(allow),
            "fields_count": len(allow),
        }
    }
