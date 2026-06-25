# agent/doc_followup/service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple
import json

from ..llm_utils.ollama_client import call_llm
from .config import load_doc_followup_config_from_env, DocFollowupConfig
from .prompts import build_followup_system_prompt
from .parsing import extract_uuid_candidates, parse_target_index
from .fetcher import fetch_docs_by_uuid
from .slicer import slice_docs_for_instruction


def ask_with_doc_followup(
    instruction: str,
    uuids: Optional[List[str]] = None,
    index_hint: Optional[str] = None,
    refno_uuid_map: Optional[Dict[int, str]] = None,  # ref_no -> uuid
    index_candidates: Optional[List[str]] = None,
    cfg: Optional[DocFollowupConfig] = None,
) -> Dict[str, Any]:
    """
    - 若 refno_uuid_map 有值：citation 模式（index = ref_no）
    - 否則：uuid 模式（index = 1..N）
    """
    cfg = cfg or load_doc_followup_config_from_env()
    instruction = (instruction or "").strip()

    # 統一輸出：避免 Word/Markdown 漏「使用者提問」
    base = {
        "question": instruction,
        "query_meta": {"refined_question": instruction},
    }

    docs: List[Dict[str, Any]] = []
    used_indexes: Set[str] = set()
    mode = "uuid"

    # ========== A) citation 模式 ==========
    if refno_uuid_map:
        mode = "refno"

        target_idx = parse_target_index(instruction)
        if target_idx is not None and target_idx in refno_uuid_map:
            ref_nos = [target_idx]
        else:
            ref_nos = sorted(refno_uuid_map.keys())

        # ref_no, uuid pairing + 去重 uuid 以減少 ES 查詢次數
        ref_pairs: List[Tuple[int, str]] = []
        seen_uuid: set[str] = set()
        fetch_uuids: List[str] = []
        #print("refno_uuid_map in ask_with_doc_followup", refno_uuid_map)
        for ref_no in ref_nos:
            u = refno_uuid_map.get(ref_no)
            if not u:
                continue
            ref_pairs.append((ref_no, u))
            if u not in seen_uuid:
                seen_uuid.add(u)
                fetch_uuids.append(u)

        if not fetch_uuids:
            return {
                **base,
                "answer": "refno_uuid_map 中沒有對應可用的 UUID，無法進行文件後續處理。",
                "citations": [],
                "reasoning": f"refno_uuid_map={refno_uuid_map!r}，但沒有任何有效的 uuid。",
                "used_uuids": [],
            }
        #print("start to call fetch_docs_by_uuid in ask_with_doc_followup")
        base_docs_list, used_indexes = fetch_docs_by_uuid(
            fetch_uuids,
            index_hint=index_hint,
            index_candidates=index_candidates,
        )
        #print("base_docs_list in ask_with_doc_followup", ask_with_doc_followup)
        base_docs = {d.get("uuid"): d for d in base_docs_list if d.get("uuid")}

        if not base_docs:
            return {
                **base,
                "answer": "查無任何與指定 citation 對應的文件，請確認資料是否仍存在於索引中。",
                "citations": [],
                "reasoning": f"refno_uuid_map={refno_uuid_map!r}，但 ESFetchDocById 未回傳任何文件。",
                "used_uuids": [],
            }

        # 依 ref_no 展開，讓 index = ref_no
        for ref_no, u in ref_pairs:
            base_doc = base_docs.get(u)
            if not base_doc:
                continue
            d = dict(base_doc)
            d["index"] = ref_no
            docs.append(d)

    # ========== B) uuid 模式 ==========
    else:
        cand = extract_uuid_candidates(instruction, max_n=cfg.max_uuid_candidates)

        clean: List[str] = []
        for u in (uuids or []):
            if isinstance(u, str):
                s = u.strip()
                if s and s not in clean:
                    clean.append(s)
        for u in cand:
            if u not in clean:
                clean.append(u)

        if not clean:
            return {
                **base,
                "answer": "目前沒有可用的參考文件或指定的 UUID，因此無法進行這一輪的指令。",
                "citations": [],
                "reasoning": "呼叫端未提供 uuids，且在指令中也未偵測到可用的 UUID/hash。",
                "used_uuids": [],
            }

        base_docs_list, used_indexes = fetch_docs_by_uuid(
            clean,
            index_hint=index_hint,
            index_candidates=index_candidates,
        )

        if not base_docs_list:
            return {
                **base,
                "answer": "查無任何與指定 UUID 對應的文件，請確認字串是否正確，或是否存在於目前的索引中。",
                "citations": [],
                "reasoning": f"指定的 UUID 列表為 {clean!r}，但 ESFetchDocById 未回傳任何文件。",
                "used_uuids": [],
            }

        for idx, d in enumerate(base_docs_list, start=1):
            nd = dict(d)
            nd["index"] = idx
            docs.append(nd)

    if not docs:
        return {
            **base,
            "answer": "目前沒有可用的文件可供後續處理。",
            "citations": [],
            "reasoning": f"mode={mode!r}，但 docs 為空。",
            "used_uuids": [],
        }

    sliced_docs = slice_docs_for_instruction(cfg, instruction, docs)

    payload = {"instruction": instruction, "docs": sliced_docs}
    user_prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    sys_prompt = build_followup_system_prompt(cfg)

    answer = call_llm(
        user_prompt,
        system_prompt=sys_prompt,
        extra_params={"options": {}},
        timeout=cfg.followup_timeout_sec,
    )

    used_uuids: List[str] = []
    for d in docs:
        u = d.get("uuid")
        if u and u not in used_uuids:
            used_uuids.append(u)

    used_indexes_list = sorted(used_indexes) if used_indexes else []

    reasoning = (
        "依照前一輪報告中的 citation 編號（ref_no）對應到原始文件，進行本輪的後續處理。"
        if mode == "refno"
        else "僅依據呼叫端提供或在指令中偵測到的 UUID 所對應的文件全文（或片段）進行後續處理。"
    )

    return {
        **base,
        "answer": answer,
        "citations": [],
        "reasoning": reasoning,
        "used_uuids": used_uuids,
        "doc_count": len(docs),
        "used_indexes": used_indexes_list,
    }
