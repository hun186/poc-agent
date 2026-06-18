from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document

from api.services.export_word_service import ExportWordService


def _paragraph_texts(docx_bytes: bytes) -> list[str]:
    doc = Document(BytesIO(docx_bytes))
    return [paragraph.text for paragraph in doc.paragraphs]


def test_export_docx_adds_answer_heading_after_user_question() -> None:
    docx_bytes, filename = ExportWordService().build_docx_bytes(
        {
            "question": "這份資料的重點是什麼？",
            "answer": "重點摘要如下。",
        }
    )

    assert filename.endswith(".docx")
    paragraphs = _paragraph_texts(docx_bytes)
    assert "使用者提問" in paragraphs
    assert "AI 代理人回答" in paragraphs
    assert paragraphs.index("使用者提問") < paragraphs.index("AI 代理人回答")
    assert paragraphs.index("AI 代理人回答") < paragraphs.index("重點摘要如下。")


def test_export_docx_answer_heading_does_not_remove_numbered_report_sections() -> None:
    docx_bytes, _ = ExportWordService().build_docx_bytes(
        {
            "question": "請綜整漁船祥發23號的活動樣態。",
            "answer": "\n".join(
                [
                    "**一、資料概況**",
                    "- 文件數 / 片段數：6 / 6",
                    "",
                    "**二、活動時間線（依日期排列）**",
                    "- 2026-05-25：東石漁港外海活動。",
                    "",
                    "**三、趨勢分析**",
                    "1. 作業區域變化",
                ]
            ),
        }
    )

    doc = Document(BytesIO(docx_bytes))
    paragraph_texts = [paragraph.text for paragraph in doc.paragraphs]
    paragraph_styles = {paragraph.text: paragraph.style.name for paragraph in doc.paragraphs}

    assert paragraph_texts.index("AI 代理人回答") < paragraph_texts.index("一、資料概況")
    assert paragraph_texts.index("一、資料概況") < paragraph_texts.index("二、活動時間線（依日期排列）")
    assert paragraph_texts.index("二、活動時間線（依日期排列）") < paragraph_texts.index("三、趨勢分析")
    assert paragraph_styles["一、資料概況"] == "Heading 2"
    assert paragraph_styles["二、活動時間線（依日期排列）"] == "Heading 2"
    assert paragraph_styles["三、趨勢分析"] == "Heading 2"


def test_export_docx_answer_heading_preserves_markdown_table_smart_merge() -> None:
    docx_bytes, _ = ExportWordService().build_docx_bytes(
        {
            "question": "請綜整漁船祥發23號的活動樣態。",
            "answer": "\n".join(
                [
                    "**二、活動時間線（依日期排列）**",
                    "| 船名 | 海域 | 日期 | 活動 |",
                    "| --- | --- | --- | --- |",
                    "| 祥發23號 | 東石外海 | 2026-05-25 | 作業 |",
                    "| 祥發23號 | 東石外海 | 2026-05-28 | 移動 |",
                    "| 祥發23號 | 八斗子 | 2026-05-29 | 返港 |",
                ]
            ),
        }
    )

    doc = Document(BytesIO(docx_bytes))
    paragraph_texts = [paragraph.text for paragraph in doc.paragraphs]

    assert paragraph_texts.index("AI 代理人回答") < paragraph_texts.index("二、活動時間線（依日期排列）")
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert [table.cell(0, col).text for col in range(4)] == ["船名", "海域", "日期", "活動"]
    assert table.cell(1, 0)._tc is table.cell(2, 0)._tc
    assert table.cell(1, 1)._tc is table.cell(2, 1)._tc
    assert table.cell(1, 2)._tc is not table.cell(2, 2)._tc
