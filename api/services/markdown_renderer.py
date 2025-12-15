#api/services/markdown_renderer.py
import os
import re
import html
import json
from typing import Any
from fastapi import Request
from api.core.url_utils import abs_url

def render_markdown(out: Any, request: Request) -> str:
    """
    把代理人輸出（dict 或 str）轉成排版好的 Markdown：
    - 回答主文（支援把 <em>/<i>/<strong>/<b>/<br>/<p> 轉成 Markdown）
    - 引用來源（含段落、縮短引文、可點連結）
    - 可展開的「推理步驟」與「原始 JSON」
    """
    ALLOW_DETAILS = os.getenv("MD_ALLOW_DETAILS", "1") == "1"  # ← 是否輸出 <details>（預設開）

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
        return s.replace("\r\n", "\n").replace("\\n", "\n")

    # 3) 綜合正規化
    def _normalize_text(s: str) -> str:
        return _normalize_newlines(_html_to_markdown_light(s)).strip()

    # out 是字串就直接回傳（也正規化一次）
    if not isinstance(out, dict):
        return _normalize_text(str(out))

    # 取欄位 & 正規化
    answer = _normalize_text(out.get("answer") or "")
    reasoning = _normalize_text(out.get("reasoning") or "")
    citations = out.get("citations") or []

    # ★ 新增：資料整備代理人 log
    data_agent = out.get("data_agent") or {}
    da_runs = data_agent.get("runs") or []
    
    # 把 citation 的 text 也處理（避免 <em> 顯示失敗）
    for c in citations:
        if isinstance(c.get("text"), str):
            c["text"] = _normalize_text(c["text"])

    md: list[str] = []

    # 主文
    if answer:
        md.append("# 回答\n")
        md.append(answer)

    # 引用來源
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

    # === 資料整備紀錄（Data Agent）===
    if da_runs:
        last_run = da_runs[-1]  # 通常就是這次回答對應的那一輪
        mode = last_run.get("mode") or out.get("mode")
        elapsed = last_run.get("elapsed_sec")
        question_raw = last_run.get("question") or out.get("question") or out.get("q")

        stats = last_run.get("stats") or {}
        query_meta = last_run.get("query_meta") or {}
        time_range = last_run.get("time_range") or {}

        md.append("\n\n## 資料整備紀錄（Data Agent）\n")
        if mode:
            md.append(f"- 模式：`{mode}`")
        if elapsed is not None:
            md.append(f"- 資料準備耗時：約 **{elapsed} 秒**")
        if question_raw:
            md.append(f"- 原始問題：{question_raw}")

        # 時間範圍（report 模式常用；style 通常沒有就顯示 N/A）
        dt_from = time_range.get("date_from") or query_meta.get("date_from")
        dt_to = time_range.get("date_to") or query_meta.get("date_to")
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
        core_terms = (
            query_meta.get("core_terms")
            or last_run.get("core_terms")
            or []
        )
        topic_terms = (
            query_meta.get("topic_terms")
            or last_run.get("topic_terms")
            or []
        )
        style_terms = (
            query_meta.get("style_terms")
            or last_run.get("style_terms")
            or []
        )

        syn_terms = query_meta.get("syn_terms") or []
        effective_terms = query_meta.get("effective_terms") or []

        # report 模式：走「核心關鍵詞」語意
        if mode == "report":
            if core_terms:
                md.append(f"- 核心關鍵詞：`{', '.join(core_terms)}`")
            if topic_terms:
                md.append(f"- 主題關鍵詞：`{', '.join(topic_terms)}`")

        # style 模式：清楚分成風格關鍵詞 / 主題關鍵詞 / 合併後核心詞
        elif mode == "style":
            if style_terms:
                md.append(f"- 風格關鍵詞（style_terms）：`{', '.join(style_terms)}`")
            if topic_terms:
                md.append(f"- 主題關鍵詞（topic_terms）：`{', '.join(topic_terms)}`")
            if core_terms:
                md.append(f"- 檢索核心關鍵詞（style_terms + topic_terms）：`{', '.join(core_terms)}`")

        # 共同欄位：同義詞 / effective_terms / ES query
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

        # ES 查詢字串：依模式選擇來源
        es_query = (
            query_meta.get("es_query")
            or query_meta.get("core_query")
        )
        # 風格模式可以多退一步用 style_query
        if mode == "style" and not es_query:
            es_query = last_run.get("style_query")

        if es_query:
            md.append(f"- ES 查詢字串：`{es_query}`")
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
    print("[render_markdown] json_line_count =", json_line_count, "AUTO_COLLAPSE_JSON =", AUTO_COLLAPSE_JSON)



    return "\n\n".join(md)