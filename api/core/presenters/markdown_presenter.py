#api/services/markdown_renderer.py
import os
from typing import List, Optional
from fastapi import Request
from api.core.url_utils import abs_url
from api.core.presenters.citation_views import build_citation_views

#from api.core.presenters.extractors import extract_presentation
from api.core.presenters.sections import AgentPresentation, DataAgentSection

#from api.core.presenters.text_sanitize import normalize_text_for_markdown

def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())

def _wrap_long_section(title: str, body: str, *, allow_details: bool, codeblock: bool = True) -> List[str]:
    """
    取代 <details>：用「標題 +（可選）code block」來壓縮長內容。
    - allow_details=True：用 code block（視覺上比較不吵）
    - allow_details=False：直接展開
    """
    body = (body or "").strip()
    if not body:
        return []

    if allow_details and codeblock:
        return [f"## {title}\n", "```text\n" + body + "\n```"]

    return [f"## {title}\n", body]

def _render_question_block(pres: AgentPresentation, *, allow_details: bool) -> List[str]:
    q_pres = _norm(getattr(pres, "question", "") or "")

    da = getattr(pres, "da_section", None)
    q_raw = _norm(getattr(da, "question_raw", "") or "")  # ✅ 真正原問句
    q0 = q_pres or q_raw                                  # ✅ 用得到的那個當原問句

    query_meta = getattr(pres, "query_meta", None)
    q_ref = ""
    if isinstance(query_meta, dict):
        q_ref = _norm(str(query_meta.get("refined_question") or ""))

    if not q_ref and da:
        q_ref = _norm(str(getattr(da, "refined_question", "") or ""))

    if not q0 and not q_ref:
        return []

    out: List[str] = ["## 使用者提問\n"]
    if q0:
        out.append(f"- 原始提問：{q0}")

    # ✅ 只有真的不同才顯示
    if q_ref and q_ref != q0:
        out.append(f"- 精煉提問（檢索用）：{q_ref}")

    return out

def _render_question_block_1229(pres: AgentPresentation, *, allow_details: bool) -> List[str]:
    """
    顯示「使用者提問」與「精煉提問」。
    - 原問句：優先用 pres.question（你 payload["question"] 通常會映射到這）
    - 精煉問句：優先找 pres.query_meta["refined_question"]，找不到就從 da_section 嘗試拿
    """
    q0 = (getattr(pres, "question", None) or "").strip()

    query_meta = getattr(pres, "query_meta", None)
    q_ref = ""
    if isinstance(query_meta, dict):
        q_ref = str(query_meta.get("refined_question") or "").strip()

    if not q_ref:
        da = getattr(pres, "da_section", None)
        q_ref = str(getattr(da, "refined_question", "") or "").strip()

    if not q0 and not q_ref:
        return []

    out: List[str] = ["## 使用者提問\n"]
    #if q0:
    #    out.append(f"- 原始提問：{q0}")

    # 只有在「真的不同」時才顯示精煉（避免噪音）
    if q_ref and q_ref != q0:
        if allow_details:
            out.extend([
                "精煉後提問（檢索用）\n\n",
                f"{q_ref}\n",
            ])
        else:
            out.append(f"- 精煉提問：{q_ref}")

    return out


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
    md.extend(_render_download_link(request, session_id, getattr(pres, "turn_id", None)))
    # ✅ 新增：先渲染提問（原問句 + 精煉問句）
    md.extend(_render_question_block(pres, allow_details=allow_details))
    md.extend(_render_answer(pres))
    md.extend(_render_citations(pres, request))
    #md.extend(_render_citations(pres, request, allow_details=allow_details))
    #md.extend(_render_data_agent(pres.da_section))
    md.extend(_render_data_agent(pres.da_section, allow_details=allow_details))
    md.extend(_render_reasoning(pres, allow_details=allow_details))
    md.extend(_render_raw_json(pres, allow_details=allow_details))
    return "\n\n".join([x for x in md if x and x.strip()])


def _render_download_link(request: Request, session_id: Optional[str], turn_id: Optional[str]) -> List[str]:
    if not session_id:
        return []
    q = f"/v1/export/word?session_id={session_id}"
    if turn_id:
        q += f"&turn_id={turn_id}"
    download_url = abs_url(request, q)
    return [f"[⬇ 下載為 Word]({download_url})\n"]

'''
def _render_download_link(request: Request, session_id: Optional[str]) -> List[str]:
    if not session_id:
        return []
    download_url = abs_url(request, f"/v1/export/word?session_id={session_id}")
    return [f"[⬇ 下載為 Word]({download_url})\n"]
'''


def _render_answer(pres: AgentPresentation) -> List[str]:
    if not pres.answer:
        return []
    return ["## 回答\n", pres.answer]

'''
def _render_citations(pres: AgentPresentation, request: Request, *, allow_details: bool = True) -> List[str]:
    if not pres.citations:
        return []

    lines: List[str] = ["## 來源 / Citations\n"]
    views = build_citation_views(pres.citations, request)

    for v in views:
        pid_str = f"（段落 {v.paragraph_id}）" if v.paragraph_id else ""
        date_piece = f" · 🗓 {v.date_iso}" if v.date_iso else ""

        link = ""
        if v.doc_id and v.url_es and v.url_json and v.url_txt:
            uuid_link = f"[{v.doc_id}]({v.url_es})"
            link = f" · UUID: {uuid_link} · [JSON]({v.url_json}) · [下載全文]({v.url_txt})"

        lines.append(f"{v.label} **{v.display}**{pid_str}{link}{date_piece}\n\n   > {v.short_text}")
    if allow_details:
        body = "\n\n".join(lines)
        return _wrap_long_section("來源 / Citations", body, allow_details=allow_details)

    return lines
'''

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

def _render_data_agent(da_section: Optional[DataAgentSection], *, allow_details: bool = True) -> List[str]:
    if not da_section:
        return []

    mode = da_section.mode
    elapsed = da_section.elapsed_sec
    question_raw = da_section.question_raw
    refined_question = getattr(da_section, "refined_question", None)

    stats = da_section.stats or {}
    dt_from = getattr(da_section, "date_from", None)
    dt_to = getattr(da_section, "date_to", None)

    core_terms = da_section.core_terms or []
    topic_terms = getattr(da_section, "topic_terms", None) or []
    style_terms = getattr(da_section, "style_terms", None) or []

    syn_terms = da_section.syn_terms or []
    effective_terms = da_section.effective_terms or []
    es_query = da_section.es_query

    def _truncate(s: str, n: int = 1000) -> str:
        s = s or ""
        return s if len(s) <= n else (s[:n] + "…")

    lines: List[str] = []

    if mode:
        lines.append(f"- 模式：`{mode}`")
    if elapsed is not None:
        lines.append(f"- 資料準備耗時：約 **{elapsed} 秒**")
    if question_raw:
        lines.append(f"- 原始問題：{question_raw}")
    if refined_question:
        lines.append(f"- 精煉後問題（檢索用）：{refined_question}")

    if dt_from or dt_to:
        lines.append(f"- 查詢時間範圍：`{dt_from or 'N/A'}` ～ `{dt_to or 'N/A'}`")

    # 統計概況
    if stats:
        parts = []
        doc_cnt = stats.get("doc_count")
        snip_cnt = stats.get("snippet_count")
        active_days = stats.get("active_days")
        full_doc_count = stats.get("full_doc_count")

        if doc_cnt is not None:
            parts.append(f"文件數：{doc_cnt}")
        if snip_cnt is not None:
            parts.append(f"片段數：{snip_cnt}")
        if active_days is not None:
            parts.append(f"有活動天數：{active_days}")
        if full_doc_count is not None:
            parts.append(f"風格樣本文檔數：{full_doc_count}")

        if parts:
            lines.append("- 統計概況：" + "；".join(parts))

    # 關鍵詞：依 mode 顯示（你 style/report 的欄位本來就不同）
    mode_norm = str(mode or "").lower()

    if mode_norm in ("report", "sra_report"):
        if core_terms:
            lines.append(f"- 核心關鍵詞：`{', '.join(core_terms)}`")

    elif mode_norm in ("style", "sra_style"):
        if style_terms:
            lines.append(f"- 風格關鍵詞（style_terms）：`{', '.join(style_terms)}`")
        if topic_terms:
            lines.append(f"- 主題關鍵詞（topic_terms）：`{', '.join(topic_terms)}`")
        if core_terms:
            lines.append(f"- 檢索核心關鍵詞（style_terms + topic_terms）：`{', '.join(core_terms)}`")
    else:
        # 其他模式：保守顯示 core_terms
        if core_terms:
            lines.append(f"- 核心關鍵詞：`{', '.join(core_terms)}`")

    if es_query:
        lines.append(f"- 代理人 ES 文本查詢字串：`{_truncate(str(es_query), 1200)}`")

    if syn_terms:
        lines.append(f"- 同義／擴充關鍵詞：`{_truncate(', '.join(map(str, syn_terms)), 1200)}`")

    if effective_terms:
        lines.append(f"- 實際使用關鍵詞（effective terms）：`{_truncate(', '.join(map(str, effective_terms)), 1200)}`")

    style_docs = getattr(da_section, "style_docs", None) or []
    if style_docs:
        lines.append(f"- 風格參考文本數：{len(style_docs)}")
        previews = []
        for sd in style_docs[:5]:
            t = (sd.get("article_title") or sd.get("subject") or sd.get("uuid") or "").strip()
            if t:
                previews.append(t)
        if previews:
            lines.append(f"- 風格參考（前 5）：`{_truncate('、'.join(previews), 600)}`")
            
    # ✅ allow_details=True：details 裡只放條列（不要再塞 ## 標題，避免 renderer 吃掉）
    #if allow_details:
    #    body = "\n".join(lines)
    #    return _wrap_long_section("資料整備紀錄（Data Agent）", body, allow_details=allow_details)

    # ✅ 不收合：正常章節
    return ["## 資料整備紀錄（Data Agent）\n"] + lines

def _render_answer_1229(pres: AgentPresentation) -> List[str]:
    if not pres.answer:
        return []
    return ["# 回答\n", pres.answer]


def _render_citations_1229(pres: AgentPresentation, request: Request) -> List[str]:
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


def _render_data_agent_1229(da_section: Optional[DataAgentSection]) -> List[str]:
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
        if len(syn_str) > 1000:
            syn_str = syn_str[:1000] + "…"
        md.append(f"- 同義／擴充關鍵詞：`{syn_str}`")

    if effective_terms:
        eff_str = ", ".join(effective_terms)
        if len(eff_str) > 1000:
            eff_str = eff_str[:1000] + "…"
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
'''
def _render_reasoning(pres: AgentPresentation, *, allow_details: bool) -> List[str]:
    if not pres.reasoning:
        return []

    # reasoning 是純文字步驟，適合用 code block 壓縮
    return _wrap_long_section("推理 / 步驟", pres.reasoning, allow_details=allow_details, codeblock=True)



def _render_raw_json(pres: AgentPresentation, *, allow_details: bool) -> List[str]:
    """
    raw json：pres.raw_json_md 通常已經是 Markdown（很可能包含 ```json）。
    所以這裡不要再用 ```text 包一次，避免 code fence 套 code fence。
    """
    body = (pres.raw_json_md or "").strip()
    if not body:
        return []

    # auto_collapse_json 以前是用 <details> 自動收合
    # 現在改成：allow_details=True 用「標題 + 直接放內容」，視覺上仍可接受
    title = "原始 JSON（內容較長）" if pres.auto_collapse_json else "原始 JSON"

    # raw_json_md 已經是 markdown（通常含 ```json），不要再包 ```text
    return _wrap_long_section(title, body, allow_details=allow_details, codeblock=False)

'''
