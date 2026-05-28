# agent/refiners/query_refiner.py
from __future__ import annotations

import os
import json
import time
import re
from typing import Any, Dict, Optional, Tuple

from agent.llm_utils.ollama_client import call_llm


def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).strip() == "1"


# ✅ 只套用在 report：預設關閉，避免每次都打 LLM
REFINER_REPORT_ENABLED = _env_bool("QUERY_REFINER_REPORT_ENABLED", "0")

REFINER_MODEL_ID = (
    os.getenv("QUERY_REFINER_MODEL_ID")
    or os.getenv("MODEL_ID")
    or "gpt-oss:120b-32k"
)
REFINER_TIMEOUT = float(os.getenv("QUERY_REFINER_TIMEOUT", "20"))

# 可選：要不要把完整 prompt/raw_response 記到 trace（通常很肥）
REFINER_TRACE_VERBOSE = _env_bool("QUERY_REFINER_TRACE_VERBOSE", "0")


REFINER_SYSTEM_PROMPT = """
你是一個「問句精煉器」，只做一件事：把使用者問句改寫成更精要、可供檢索與統計的版本。

請輸出 JSON，格式：
{
  "refined_question": "..."
}

規則：
1) 保留：主題/對象、地點、時間範圍、使用者要的輸出型態（整理/比較/趨勢/引用來源/SWOT 等），與資料庫檢索工具設定相關的指示，資料庫及關鍵字設定指示。
2) 刪除：客套話、重複描述、長度要求（如 2000 字）、格式碎念（如「請用漂亮小標」）、與檢索無關的冗詞。
3) 不能新增新事實（例如新增年份、地點、人物）。
4) 若原問句本來就很精簡，refined_question 直接回傳原句即可。
5) 不限制簡體或繁體；保留使用者原本用字，避免因字形轉換造成關鍵字限縮。
""".strip()


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _safe_parse_refined_question(raw: str, fallback: str) -> Tuple[str, str]:
    """
    回傳 (refined_question, parse_note)
    盡量容錯：如果 LLM 有多講話，抓第一段 JSON 來 parse。
    """
    if not raw:
        return fallback, "empty_response"

    try:
        data = json.loads(raw)
        refined = str(data.get("refined_question") or "").strip()
        return (refined or fallback), "json_ok"
    except Exception:
        pass

    m = _JSON_OBJ_RE.search(raw)
    if m:
        try:
            data = json.loads(m.group(0))
            refined = str(data.get("refined_question") or "").strip()
            return (refined or fallback), "json_extracted_ok"
        except Exception:
            return fallback, "json_extracted_but_parse_failed"

    return fallback, "no_json_found"


def refine_question_for_data_agent(
    user_question: str,
    *,
    mode: str = "report",
    trace: Optional[Dict[str, Any]] = None,
    index_hint: str | None = None,   # ✅ 新增這行
) -> str:
    """
    回傳精煉後問句；失敗就回傳原句。
    - 僅在 mode=report 時啟用（符合你「只套用在 report」的需求）
    - 成功/失敗都會寫摘要到 trace["query_refiner"]["report"]
    - verbose 才會把完整 prompt/raw_response 寫到 trace["llm"]["refiner"]
    """
    q0 = (user_question or "").strip()
    if not q0:
        return q0

    # ✅ 別用 trace = trace or {}（外面傳 {} 進來會被你換掉）
    if trace is None:
        trace = {}

    mode_norm = (mode or "").strip().lower()
    enabled = bool(REFINER_REPORT_ENABLED and mode_norm in ("report", "sra_report"))

    # 先把「摘要」的 root 準備好（即使 disabled 也可記）
    qr_root = trace.setdefault("query_refiner", {}).setdefault("report", {})
    qr_root.update({
        "enabled": enabled,
        "mode": mode,
        "input_question": q0,
        "index_hint": index_hint,   # ✅ 可選
    })

    if not enabled:
        qr_root.update({
            "output_question": q0,
            "changed": False,
            "note": "disabled",
        })
        return q0

    user_prompt = (
        "請精煉下列使用者問句，只輸出 JSON。\n\n"
        f"【使用者問句】\n{q0}\n"
    )

    t0 = time.perf_counter()
    raw = ""
    try:
        raw = call_llm(
            user_prompt,
            system_prompt=REFINER_SYSTEM_PROMPT,
            extra_params={"options": {}},
            timeout=REFINER_TIMEOUT,
            model=REFINER_MODEL_ID,
        )
        refined, parse_note = _safe_parse_refined_question(raw, q0)

        # 保護：避免變空、避免變太短（你也可以改門檻）
        if not refined or len(refined) < 4:
            refined = q0
            parse_note = f"{parse_note}; too_short_fallback"

        changed = (refined.strip() != q0)
        qr_root.update({
            "output_question": refined,
            "changed": changed,
            "note": f"parse={parse_note}",
        })

        return refined

    except Exception as e:
        qr_root.update({
            "output_question": q0,
            "changed": False,
            "note": f"error={type(e).__name__}: {e}",
        })
        return q0

    finally:
        t1 = time.perf_counter()
        qr_root["elapsed_sec"] = round(t1 - t0, 3)
        qr_root["model_id"] = REFINER_MODEL_ID
        qr_root["timeout_sec"] = REFINER_TIMEOUT

        # 可選：才把完整 prompt/raw_response 記下來（避免 trace 爆肥）
        if REFINER_TRACE_VERBOSE:
            ref_list = trace.setdefault("llm", {}).setdefault("refiner", [])
            ref_list.append({
                "system": "REFINER_SYSTEM_PROMPT",
                "user": user_prompt,
                "raw_response": raw,
                "elapsed_sec": qr_root.get("elapsed_sec"),
                "model_id": REFINER_MODEL_ID,
                "mode": mode,
            })
