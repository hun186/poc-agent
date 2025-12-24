#api/services/markdown_renderer.py
import os
from typing import List, Optional
from fastapi import Request
from api.core.url_utils import abs_url
from api.core.presenters.citation_views import build_citation_views

#from api.core.presenters.extractors import extract_presentation
from api.core.presenters.sections import AgentPresentation, DataAgentSection

#from api.core.presenters.text_sanitize import normalize_text_for_markdown

def build_markdown(
    pres: AgentPresentation,
    request: Request,
    session_id: Optional[str] = None,
) -> str:
    """
    將 AgentPresentation 轉成 Markdown（段落化，便於維護）。
    """
    allow_details = os.getenv("MD_ALLOW_DETAILS", "1") == "1"

    md: List[str] = []
    md.extend(_render_download_link(request, session_id))
    md.extend(_render_answer(pres))
    md.extend(_render_citations(pres, request))
    md.extend(_render_data_agent(pres.da_section))
    md.extend(_render_reasoning(pres, allow_details=allow_details))
    md.extend(_render_raw_json(pres, allow_details=allow_details))
    return "\n\n".join([x for x in md if x and x.strip()])


def _render_download_link(request: Request, session_id: Optional[str]) -> List[str]:
    if not session_id:
        return []
    download_url = abs_url(request, f"/v1/export/word?session_id={session_id}")
    return [f"[⬇ 下載為 Word]({download_url})\n"]


def _render_answer(pres: AgentPresentation) -> List[str]:
    if not pres.answer:
        return []
    return ["# 回答\n", pres.answer]


def _render_citations(pres: AgentPresentation, request: Request) -> List[str]:
    if not pres.citations:
        return []

    out: List[str] = ["## 來源 / Citations\n"]
    views = build_citation_views(pres.citations, request)

    for v in views:
        pid_str = f"（段落 {v.paragraph_id}）" if v.paragraph_id else ""
        date_piece = f" · 🗓 {v.date_iso}" if v.date_iso else ""

        link = ""
        if v.doc_id and v.url_es and v.url_json and v.url_txt:
            uuid_link = f"[{v.doc_id}]({v.url_es})"
            link = f" · UUID: {uuid_link} · [JSON]({v.url_json}) · [下載全文]({v.url_txt})"

        out.append(f"{v.label} **{v.display}**{pid_str}{link}{date_piece}\n\n   > {v.short_text}")

    return out


def _render_data_agent(da_section: Optional[DataAgentSection]) -> List[str]:
    if not da_section:
        return []

    md: List[str] = ["## 資料整備紀錄（Data Agent）\n"]

    mode = da_section.mode
    elapsed = da_section.elapsed_sec
    question_raw = da_section.question_raw

    stats = da_section.stats or {}
    dt_from = da_section.date_from
    dt_to = da_section.date_to

    core_terms = da_section.core_terms or []
    topic_terms = da_section.topic_terms or []
    style_terms = da_section.style_terms or []

    syn_terms = da_section.syn_terms or []
    effective_terms = da_section.effective_terms or []

    es_query = da_section.es_query

    if mode:
        md.append(f"- 模式：`{mode}`")
    if elapsed is not None:
        md.append(f"- 資料準備耗時：約 **{elapsed} 秒**")
    if question_raw:
        md.append(f"- 原始問題：{question_raw}")

    if dt_from or dt_to:
        md.append(f"- 查詢時間範圍：`{dt_from or 'N/A'}` ～ `{dt_to or 'N/A'}`")

    # 統計資訊
    if stats:
        doc_cnt = stats.get("doc_count")
        snip_cnt = stats.get("snippet_count")
        active_days = stats.get("active_days")
        full_doc_count = stats.get("full_doc_count")

        parts = []
        if doc_cnt is not None:
            parts.append(f"文件數：{doc_cnt}")
        if snip_cnt is not None:
            parts.append(f"片段數：{snip_cnt}")
        if active_days is not None:
            parts.append(f"有活動天數：{active_days}")
        if full_doc_count is not None:
            parts.append(f"風格樣本文檔數：{full_doc_count}")

        if parts:
            md.append("- 統計概況：" + "；".join(parts))

    # 關鍵字樣態：依 mode 分流
    mode_norm = str(mode or "").lower()

    if mode_norm in ("report", "sra_report"):
        if core_terms:
            md.append(f"- 核心關鍵詞：`{', '.join(core_terms)}`")

    elif mode_norm in ("style", "sra_style"):
        if style_terms:
            md.append(f"- 風格關鍵詞（style_terms）：`{', '.join(style_terms)}`")
        if topic_terms:
            md.append(f"- 主題關鍵詞（topic_terms）：`{', '.join(topic_terms)}`")
        if core_terms:
            md.append(f"- 檢索核心關鍵詞（style_terms + topic_terms）：`{', '.join(core_terms)}`")

    if es_query:
        md.append(f"- 代理人ES文本查詢工具查詢字串：`{es_query}`")

    if syn_terms:
        syn_str = ", ".join(syn_terms)
        if len(syn_str) > 120:
            syn_str = syn_str[:120] + "…"
        md.append(f"- 同義／擴充關鍵詞：`{syn_str}`")

    if effective_terms:
        eff_str = ", ".join(effective_terms)
        if len(eff_str) > 120:
            eff_str = eff_str[:120] + "…"
        md.append(f"- 實際使用關鍵詞（effective terms）：`{eff_str}`")

    return md


def _render_reasoning(pres: AgentPresentation, *, allow_details: bool) -> List[str]:
    if not pres.reasoning:
        return []

    if allow_details:
        return [
            "<details><summary>展開推理 / 步驟</summary>\n\n",
            "```text\n" + pres.reasoning + "\n```",
            "\n</details>",
        ]

    return [
        "## 推理 / 步驟\n",
        "```text\n" + pres.reasoning + "\n```",
    ]


def _render_raw_json(pres: AgentPresentation, *, allow_details: bool) -> List[str]:
    # raw json：用 pres.auto_collapse_json / pres.raw_json_md
    if pres.auto_collapse_json:
        return [
            "<details><summary>原始 JSON（自動收合，內容較長）</summary>\n\n",
            pres.raw_json_md,
            "\n</details>\n",
        ]

    if allow_details:
        return [
            "<details open><summary>原始 JSON</summary>\n\n",
            pres.raw_json_md,
            "\n</details>\n",
        ]

    return [
        "## 原始 JSON\n\n",
        pres.raw_json_md,
        "\n",
    ]