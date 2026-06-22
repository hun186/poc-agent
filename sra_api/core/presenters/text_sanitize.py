# api/core/presenters/text_sanitize.py
import re
import html
from typing import Any

def normalize_hyphens_for_word(text: str) -> str:
    """
    把各種特殊連字號換成一般半形減號，避免 Word 出現灰底標記。
    """
    if not isinstance(text, str):
        return text

    return (
        text
        .replace("\u2010", "-")  # hyphen
        .replace("\u2011", "-")  # non-breaking hyphen
        .replace("\u2012", "-")  # figure dash
        .replace("\u2013", "-")  # en dash
        .replace("\u2014", "-")  # em dash
        .replace("\u2212", "-")  # minus sign
    )

def html_to_markdown_light(s: Any) -> str:
    """
    保守白名單：把常見 HTML 標籤轉成 Markdown；其他標籤移除。
    用於 answer/citation text，避免 <em> 等直接露出。
    """
    if not isinstance(s, str):
        return ""
    s = html.unescape(s)

    # 換行/段落
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</p\s*>', '\n\n', s)
    s = re.sub(r'(?i)<p[^>]*>', '', s)

    # 強調/粗體
    s = re.sub(r'(?i)<(em|i)(\s+[^>]*)?>', '*', s)
    s = re.sub(r'(?i)</(em|i)\s*>', '*', s)
    s = re.sub(r'(?i)<(strong|b)(\s+[^>]*)?>', '**', s)
    s = re.sub(r'(?i)</(strong|b)\s*>', '**', s)

    # 清單（簡化）
    s = re.sub(r'(?i)</li\s*>', '\n', s)
    s = re.sub(r'(?i)<li[^>]*>', '- ', s)
    s = re.sub(r'(?i)</?(ul|ol|div|span)[^>]*>', '', s)

    # 其餘標籤移除
    s = re.sub(r'<[^>]+>', '', s)
    return s

def normalize_newlines(s: Any) -> str:
    """
    統一換行；對 \\n 做保守轉換，避免誤傷路徑/JSON。
    """
    if not isinstance(s, str):
        return ""
    s = s.replace("\r\n", "\n")
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    return s

def normalize_text_for_markdown(s: Any) -> str:
    """
    Markdown 版本正規化：HTML → MD、換行 → 正常化、去頭尾空白。
    """
    return normalize_newlines(html_to_markdown_light(s)).strip()

def normalize_text_for_docx(s: Any) -> str:
    """
    Docx 版本正規化：目前先做連字號清理 + 換行正規化。
    （不要做 html_to_markdown_light，因為 docx renderer 會自己處理 **/*）
    """
    s2 = normalize_newlines(s)
    return str(normalize_hyphens_for_word(s2)).strip() if isinstance(s2, str) else str(s2)