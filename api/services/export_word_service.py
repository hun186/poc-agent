# api/services/export_word_service.py
from io import BytesIO
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

# 先保留：Markdown-ish → Docx 的渲染（下一步再搬到 docx_presenter）
from api.core.presenters.docx_helpers import _add_markdown_to_doc

from api.core.presenters.sections import (
    extract_citations,
    extract_data_agent_section,
    extract_user_question,
)
#from api.core.presenters.text_sanitize import normalize_hyphens_for_word
from api.core.presenters.text_sanitize import normalize_text_for_docx
from api.core.presenters.docx_helpers import (
    _add_markdown_to_doc,
    add_data_agent_section,
)
from api.core.presenters.sections import extract_presentation

class ExportWordService:
    def build_docx_bytes(self, out: dict, filename: str = "agent_output.docx") -> tuple[bytes, str]:
        pres = extract_presentation(out)
        
        #answer = out.get("answer") or ""
        #reasoning = out.get("reasoning") or ""

        # ✅ 改用 sections 抽資料
        #user_q = extract_user_question(out)
        #citations = extract_citations(out)  # 已去重 + 修 text
        #da_section = extract_data_agent_section(out)

        doc = Document()

        # 預設字型
        style = doc.styles["Normal"]
        style.font.name = "標楷體"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")
        style.font.size = Pt(12)

        doc.add_heading("AI 代理人輸出報告", level=1)
        '''
        # 使用者提問
        if user_q:
            user_q = normalize_text_for_docx(user_q)
            doc.add_heading("使用者提問", level=2)
            doc.add_paragraph(user_q)

        # 回答
        if answer:
            _add_markdown_to_doc(doc, answer)

        # ✅ Data Agent
        #write_data_agent_section_docx(doc, da_section)
        add_data_agent_section(doc, da_section)

        # ✅ 引用來源：用 extract_citations(out) 的結果
        if citations:
            doc.add_page_break()
            doc.add_heading("引用來源 / Citations", level=2)
            for c in citations:
                txt = (c.get("text") or "").replace("\n", " ").strip()
                txt = normalize_text_for_docx(txt)

                uuid_ = c.get("uuid") or c.get("source_id") or c.get("doc_id") or c.get("id") or ""
                if len(txt) > 300:
                    txt = txt[:300] + "…"

                p = doc.add_paragraph(style="List Number")
                p.add_run(f"({uuid_}) {txt}")

        # 推理內容
        if reasoning:
            doc.add_page_break()
            doc.add_heading("附錄：推理內容", level=2)
            _add_markdown_to_doc(doc, reasoning)
        '''
        # 使用者提問
        if pres.user_question:
            doc.add_heading("使用者提問", level=2)
            doc.add_paragraph(normalize_text_for_docx(pres.user_question))

        # 回答（pres.answer 已是 markdown-ish，docx parser 吃得下）
        if pres.answer:
            _add_markdown_to_doc(doc, pres.answer)

        # Data Agent
        add_data_agent_section(doc, pres.da_section)

        # 引用來源
        if pres.citations:
            doc.add_page_break()
            doc.add_heading("引用來源 / Citations", level=2)
            for c in pres.citations:
                txt = (c.get("text") or "").replace("\n", " ").strip()
                txt = normalize_text_for_docx(txt)
                uuid_ = c.get("uuid") or c.get("source_id") or c.get("doc_id") or c.get("id") or ""
                if len(txt) > 300:
                    txt = txt[:300] + "…"
                p = doc.add_paragraph(style="List Number")
                p.add_run(f"({uuid_}) {txt}")

        # 推理內容
        if pres.reasoning:
            doc.add_page_break()
            doc.add_heading("附錄：推理內容", level=2)
            _add_markdown_to_doc(doc, pres.reasoning)
            
        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf.getvalue(), filename
