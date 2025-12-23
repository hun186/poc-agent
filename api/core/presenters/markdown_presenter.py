#api/services/markdown_renderer.py
import os
import re
import html
import json
from typing import Any
from fastapi import Request
from api.core.url_utils import abs_url

from api.core.presenters.sections import (
    extract_citations,
    extract_data_agent_section,
    #extract_user_question,
)

from api.core.presenters.text_sanitize import normalize_text_for_markdown
from api.core.presenters.sections import (
    extract_presentation,   # ★ 新增
)

#from api.core.presenters.text_sanitize import normalize_text_for_markdown

#def render_markdown(out: Any, request: Request) -> str:
def render_markdown(out: Any, request: Request, session_id: str | None = None) -> str:
    """
    把代理人輸出（dict 或 str）轉成排版好的 Markdown：
    - 回答主文（支援把 <em>/<i>/<strong>/<b>/<br>/<p> 轉成 Markdown）
    - 引用來源（含段落、縮短引文、可點連結）
    - 可展開的「推理步驟」與「原始 JSON」
    """
    ALLOW_DETAILS = os.getenv("MD_ALLOW_DETAILS", "1") == "1"  # ← 是否輸出 <details>（預設開）
    '''
    # 1) 把常見 HTML 轉成 Markdown（保守白名單）
    def _html_to_markdown_light(s: str) -> str:
        if not isinstance(s, str):
            return ""
        s = html.unescape(s)  # &lt;em&gt; → <em>

        # 換行/段落
        s = re.sub(r'(?i)<br\s*/?>', '\n', s)
        s = re.sub(r'(?i)</p\s*>', '\n\n', s)
        s = re.sub(r'(?i)<p[^>]*>', '', s)

        # 強調/粗體
        s = re.sub(r'(?i)<(em|i)(\s+[^>]*)?>', '*', s)
        s = re.sub(r'(?i)</(em|i)\s*>', '*', s)
        s = re.sub(r'(?i)<(strong|b)(\s+[^>]*)?>', '**', s)
        s = re.sub(r'(?i)</(strong|b)\s*>', '**', s)

        # 清單（簡化處理）
        s = re.sub(r'(?i)</li\s*>', '\n', s)
        s = re.sub(r'(?i)<li[^>]*>', '- ', s)
        s = re.sub(r'(?i)</?(ul|ol|div|span)[^>]*>', '', s)

        # 其餘標籤直接移除
        s = re.sub(r'<[^>]+>', '', s)
        return s

    # 2) 統一換行：把字面 "\\n" 變真正換行；也處理 \r\n
    def _normalize_newlines(s: str) -> str:
        if not isinstance(s, str):
            return ""
        s = s.replace("\r\n", "\n")
        if "\\n" in s and "\n" not in s:
            s = s.replace("\\n", "\n")
        return s

    # 3) 綜合正規化
    def normalize_text_for_markdown(s: str) -> str:
        return _normalize_newlines(_html_to_markdown_light(s)).strip()
    '''
    pres = extract_presentation(out)
    answer = pres.answer
    reasoning = pres.reasoning
    citations = pres.citations
    da_section = pres.da_section

   
    '''
    # out 是字串就直接回傳（也正規化一次）
    if not isinstance(out, dict):
        return normalize_text_for_markdown(str(out))

    # 取欄位 & 正規化
    answer = normalize_text_for_markdown(out.get("answer") or "")
    reasoning = normalize_text_for_markdown(out.get("reasoning") or "")
    citations = extract_citations(out)
    da_section = extract_data_agent_section(out)
    '''
    
    # ★ 新增：資料整備代理人 log
    #data_agent = out.get("data_agent") or {}
    #da_runs = data_agent.get("runs") or []
    #da_section = extract_data_agent_section(out)
    
    # 把 citation 的 text 也處理（避免 <em> 顯示失敗）
    '''
    for c in citations:
        if isinstance(c.get("text"), str):
            c["text"] = normalize_text_for_markdown(c["text"])
    '''
    md: list[str] = []

    # === 下載 Word 連結（開頭）===
    # 用 GET /v1/export/word?session_id=xxx
    if session_id:
        download_url = abs_url(request, f"/v1/export/word?session_id={session_id}")
        # 純 Markdown 連結，OpenWebUI 一定會變成可點的超連結
        md.append(f"[⬇ 下載為 Word]({download_url})\n")
    # === 使用者提問（建議放在回答前）===
    #user_q = extract_user_question(out)
    #if user_q:
    #    md.append("## 使用者提問\n")
    #    md.append(normalize_text_for_markdown(user_q))
    # 主文
    if answer:
        md.append("# 回答\n")
        md.append(answer)

    # 引用來源
    '''
    if citations:
        md.append("\n\n## 來源 / Citations\n")
        seen = set()  # 若要去掉完全重複的 citation，可以用 (doc_id, paragraph_id, text) 當 key

        for c in citations:
            doc_id = (
                c.get("uuid")
                or c.get("source_id")
                or c.get("doc_id")
                or c.get("id")
            )

            # 去掉完全重複（同文件 + 同段落 + 同文字），避免重複列出
            key = (doc_id, c.get("paragraph_id"), c.get("text"))
            if key in seen:
                continue
            seen.add(key)

            # ★ 用 ref_no / snippet_index 當顯示編號，對齊主文裡的 ① ② ③…
            ref_no = c.get("ref_no")
            if not isinstance(ref_no, int):
                # fallback：用 snippet_index（_build_citations_from_payload 已經補好）
                ref_no = c.get("snippet_index") if isinstance(c.get("snippet_index"), int) else None

            # 這裡你可以決定要用「1.」還是「①」
            if isinstance(ref_no, int):
                # 用阿拉伯數字：1.
                label = f"{ref_no}."
                # 如果你想用圈號數字可以改成：
                # circled_digits = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
                # label = circled_digits[ref_no-1] if 1 <= ref_no <= len(circled_digits) else f"{ref_no}."
            else:
                label = "-"  # 沒有 ref_no 就用無序

            # 顯示名稱：優先 subject，其次 title
            display = (
                c.get("subject")
                or c.get("article_title")
                or c.get("title")
                or (str(doc_id) if doc_id is not None else "[未知來源]")
            )

            pid = c.get("paragraph_id")
            txt = (c.get("text") or "").replace("\n", " ").strip()
            if len(txt) > 300:
                txt = txt[:300] + "…"

            link = ""
            if isinstance(doc_id, str):
                # 1) 原來的全文 JSON / 下載全文（維持現狀）
                base_full = abs_url(request, f"/v1/docs/{doc_id}/fulltext")
                url_json = base_full + "?format=json"
                url_txt  = base_full + "?format=txt&download=1"
            
                # 2) 額外：uuid 連結 → 原始 ES 完整文件
                url_es = abs_url(request, f"/v1/docs/{doc_id}")
                uuid_link = f"[{doc_id}]({url_es})"
            
                # 3) 組合成一段文字
                #    （順序可以依你喜好調整）
                link = f" · UUID: {uuid_link} · [JSON]({url_json}) · [下載全文]({url_txt})"
            else:
                link = ""

            pid_str = f"（段落 {pid}）" if pid else ""
            date_piece = f" · 🗓 {c.get('date_iso')}" if c.get("date_iso") else ""

            md.append(
                f"{label} **{display}**{pid_str}{link}{date_piece}\n\n   > {txt}"
            )
    '''
    # 引用來源（extract_citations 已做 dedupe + normalize text）
    if citations:
        md.append("\n\n## 來源 / Citations\n")
    
        for c in citations:
            doc_id = (
                c.get("uuid")
                or c.get("source_id")
                or c.get("doc_id")
                or c.get("id")
            )
    
            # ★ 用 ref_no / snippet_index 當顯示編號
            ref_no = c.get("ref_no")
            if not isinstance(ref_no, int):
                ref_no = c.get("snippet_index") if isinstance(c.get("snippet_index"), int) else None
    
            label = f"{ref_no}." if isinstance(ref_no, int) else "-"
    
            # 顯示名稱：優先 subject，其次 title
            display = (
                c.get("subject")
                or c.get("article_title")
                or c.get("title")
                or (str(doc_id) if doc_id is not None else "[未知來源]")
            )
    
            pid = c.get("paragraph_id")
    
            # ★ 注意：這裡只是「顯示用把換行壓成一行」，不是 normalize
            txt = (c.get("text") or "").replace("\n", " ").strip()
            if len(txt) > 300:
                txt = txt[:300] + "…"
    
            link = ""
            if isinstance(doc_id, str):
                base_full = abs_url(request, f"/v1/docs/{doc_id}/fulltext")
                url_json = base_full + "?format=json"
                url_txt  = base_full + "?format=txt&download=1"
    
                url_es = abs_url(request, f"/v1/docs/{doc_id}")
                uuid_link = f"[{doc_id}]({url_es})"
    
                link = f" · UUID: {uuid_link} · [JSON]({url_json}) · [下載全文]({url_txt})"
    
            pid_str = f"（段落 {pid}）" if pid else ""
            date_piece = f" · 🗓 {c.get('date_iso')}" if c.get("date_iso") else ""
    
            md.append(f"{label} **{display}**{pid_str}{link}{date_piece}\n\n   > {txt}")

    # === 資料整備紀錄（Data Agent）===
    if da_section:
        md.append("\n\n## 資料整備紀錄（Data Agent）\n")
    
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
    
        # 統計資訊（按模式略有不同）
        if stats:
            doc_cnt = stats.get("doc_count")
            snip_cnt = stats.get("snippet_count")
            active_days = stats.get("active_days")
            full_doc_count = stats.get("full_doc_count")  # 風格模式才會有
    
            line_parts = []
            if doc_cnt is not None:
                line_parts.append(f"文件數：{doc_cnt}")
            if snip_cnt is not None:
                line_parts.append(f"片段數：{snip_cnt}")
            if active_days is not None:
                line_parts.append(f"有活動天數：{active_days}")
            if full_doc_count is not None:
                line_parts.append(f"風格樣本文檔數：{full_doc_count}")
            if line_parts:
                md.append("- 統計概況：" + "；".join(line_parts))
    
        # === 關鍵字樣態：依 mode 分流 ===
        mode_norm = str(mode or "").lower()
    
        # report 模式：走「核心關鍵詞」語意
        if mode_norm in ("report", "sra_report"):
            if core_terms:
                md.append(f"- 核心關鍵詞：`{', '.join(core_terms)}`")
    
        # style 模式：清楚分成風格關鍵詞 / 主題關鍵詞 / 合併後核心詞
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

    # 推理（可收合 / fallback）
    if reasoning:
        if ALLOW_DETAILS:
            md.append("\n\n<details><summary>展開推理 / 步驟</summary>\n\n")
            md.append("```text\n" + reasoning + "\n```")
            md.append("\n</details>")
        else:
            md.append("\n\n## 推理 / 步驟\n")
            md.append("```text\n" + reasoning + "\n```")

    # 原始 JSON（可收合 / fallback 同理）
    '''
    raw_json = "```json\n" + json.dumps(out, ensure_ascii=False, indent=2) + "\n```"
    if ALLOW_DETAILS:
        md.append("\n\n<details><summary>原始 JSON</summary>\n\n")
        md.append(raw_json)
        md.append("\n</details>\n")
    else:
        md.append("\n\n## 原始 JSON\n\n")
        md.append(raw_json)
        md.append("\n")
    '''
    
    
    '''
    # === 智慧判斷：原始 JSON 是否需要預設收合 ===
    raw_json_str = json.dumps(out, ensure_ascii=False, indent=2)
    raw_json = f"```json\n{raw_json_str}\n```"

    # 粗略計算 JSON 行數
    json_line_count = raw_json_str.count("\n") + 1
    AUTO_COLLAPSE_JSON = json_line_count > 60   # ★ 超過 60 行 → 一律用收合樣式

    # debug（需要時再開）
    # print(f"[render_markdown] json_line_count={json_line_count}, AUTO_COLLAPSE_JSON={AUTO_COLLAPSE_JSON}, ALLOW_DETAILS={ALLOW_DETAILS}")

    if AUTO_COLLAPSE_JSON:
        # ★ 不管 ALLOW_DETAILS 設什麼，只要太長就一定用收合 <details>，避免畫面爆炸
        md.append("\n\n<details><summary>原始 JSON（自動收合，內容較長）</summary>\n\n")
        md.append(raw_json)
        md.append("\n</details>\n")

    else:
        # ★ 行數不多時，才依照 ALLOW_DETAILS 來決定呈現方式
        if ALLOW_DETAILS:
            # 可以預設展開（open），使用者仍可手動收合
            md.append("\n\n<details open><summary>原始 JSON</summary>\n\n")
            md.append(raw_json)
            md.append("\n</details>\n")
        else:
            # 環境不允許 <details>，就用一般標題直接顯示
            md.append("\n\n## 原始 JSON\n\n")
            md.append(raw_json)
            md.append("\n")
    if os.getenv("DEBUG_RENDER_MD", "0") == "1":
        print("[render_markdown] json_line_count =", json_line_count, "AUTO_COLLAPSE_JSON =", AUTO_COLLAPSE_JSON)
    '''
    # raw json（改用 pres.auto_collapse_json / pres.raw_json_md）
    if pres.auto_collapse_json:
        md.append("\n\n<details><summary>原始 JSON（自動收合，內容較長）</summary>\n\n")
        md.append(pres.raw_json_md)
        md.append("\n</details>\n")
    else:
        if ALLOW_DETAILS:
            md.append("\n\n<details open><summary>原始 JSON</summary>\n\n")
            md.append(pres.raw_json_md)
            md.append("\n</details>\n")
        else:
            md.append("\n\n## 原始 JSON\n\n")
            md.append(pres.raw_json_md)
            md.append("\n")

    return "\n\n".join(md)