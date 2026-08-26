# agent/refiners/query_refiner.py
from __future__ import annotations

import os
import json
import time
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
3) 不能新增新事實（例如新增地點、人物）。但日、週、月、季、年及帶數量的相對時間（如昨天、過去 10 天、上一週、前兩週、兩週前、上月、去年）必須依系統時間換算為明確日期範圍；這項換算不算新增事實。
4) 若原問句本來就很精簡，refined_question 直接回傳原句即可。
5) 不限制簡體或繁體；保留使用者原本用字，避免因字形轉換造成關鍵字限縮。
6) 判定檢索時間範圍時，以使用者的任務指令（例如「請蒐集／整理／追蹤去年……」）為最高優先；背景說明中的月份、日期或事件時間只可保留為重點時段，不得擅自把整體檢索範圍縮窄。例：任務要求蒐集「去年」資料，即使背景提到「3月間」，檢索範圍仍是去年 1 月 1 日至 12 月 31 日，3 月僅是重點時段。只有任務指令本身明確要求「去年3月」、「僅限3月」或等同限制時，才縮窄至該月。
""".strip()


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _time_reference() -> Dict[str, str]:
    timezone_name = (os.getenv("LLM_CURRENT_TIMEZONE") or "Asia/Taipei").strip()
    try:
        now = datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        timezone_name = "UTC"
        now = datetime.now(ZoneInfo("UTC"))
    current_date = now.date()
    current_week_from = current_date - timedelta(days=current_date.weekday())
    previous_week_from = current_week_from - timedelta(days=7)
    previous_week_to = current_week_from - timedelta(days=1)
    previous_two_weeks_from = current_week_from - timedelta(days=14)
    return {
        "timezone": timezone_name,
        "reference_time": now.isoformat(timespec="seconds"),
        "reference_date": current_date.isoformat(),
        "current_year": str(now.year),
        "previous_year": str(now.year - 1),
        "week_start": "monday",
        "previous_week_from": previous_week_from.isoformat(),
        "previous_week_to": previous_week_to.isoformat(),
        "previous_two_weeks_from": previous_two_weeks_from.isoformat(),
        "previous_two_weeks_to": previous_week_to.isoformat(),
    }


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
        time_reference = _time_reference()
        qr_root["time_context"] = {
            "enabled": True,
            "reason": "query_refiner_relative_date_resolution",
            **time_reference,
        }
        refiner_system_prompt = (
            f"{REFINER_SYSTEM_PROMPT}\n\n"
            "【本次時間換算基準】"
            f"reference_time={time_reference['reference_time']}，"
            f"timezone={time_reference['timezone']}，"
            f"今年={time_reference['current_year']}，去年={time_reference['previous_year']}。"
            f"若任務指令要求『去年』且未明確限縮月份，整體檢索範圍必須是 {time_reference['previous_year']}-01-01 至 {time_reference['previous_year']}-12-31；"
            "背景敘述中的月份只能標成重點時段，不得覆蓋任務指令的全年範圍。"
            "週以週一至週日為界；"
            f"上一週={time_reference['previous_week_from']} 至 {time_reference['previous_week_to']}；"
            f"前兩週（指目前週之前的兩個完整週）={time_reference['previous_two_weeks_from']} 至 {time_reference['previous_two_weeks_to']}。"
            "問句含相對時間時，refined_question 必須保留原語意並換成可供檢索的明確起訖日期；"
            "不限於上述例子，今天／昨天／過去 N 天／上一週／前 N 週／N 週前／本月／上月／今年／去年等，"
            "都必須由 reference_time 及上述週界線計算，不得依模型知識截止日猜測。"
            "『前 N 週』表示目前週之前連續 N 個完整週；『N 週前』表示往前偏移 N 週的單一完整週；"
            "『過去 N 週』則表示截至 reference_date（含當日）的滾動 N×7 天，三者不得混用。"
        )
        raw = call_llm(
            user_prompt,
            system_prompt=refiner_system_prompt,
            extra_params={"options": {}},
            timeout=REFINER_TIMEOUT,
            model=REFINER_MODEL_ID,
            include_current_time=True,
            current_time_context_reason="query_refiner_relative_date_resolution",
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
