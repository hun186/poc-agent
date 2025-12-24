# shared/http/download_filename.py
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import quote


# ----------------------------
# Public API
# ----------------------------

@dataclass(frozen=True)
class FilenameParts:
    date_yyyymmdd: str
    core_piece: str
    question_head: str
    hash8: str


def build_docx_filename_from_presentation(
    pres: object,
    *,
    fallback: str = "agent_output.docx",
    ext: str = ".docx",
    max_core_terms: int = 4,
    question_head_len: int = 24,
) -> str:
    """
    從 presentation（你現在的 AgentPresentation）產生「可讀且可含中文」的檔名。
    檔名：YYYYMMDD_核心詞_提問前N字_hash8.docx

    需求重點：
    - 檔名可保留中文（顯示給使用者看）
    - 移除 Windows 非法字元，避免下載後無法存檔
    - 加 hash8 避免覆蓋
    """
    q = _get_user_question(pres).strip()
    if not q:
        return _ensure_ext(fallback, ext)

    date = datetime.now().strftime("%Y%m%d")
    hash8 = hashlib.sha1(q.encode("utf-8")).hexdigest()[:8]

    core_terms = _get_core_terms(pres, max_core_terms=max_core_terms)
    core_join = "-".join(core_terms)
    core_piece = _safe_filename_piece_unicode(core_join, max_len=30)

    q_head = _safe_filename_piece_unicode(q[:question_head_len], max_len=question_head_len)

    parts = [date]
    if core_piece:
        parts.append(core_piece)
    if q_head:
        parts.append(q_head)
    parts.append(hash8)

    name = "_".join([p for p in parts if p])
    name = _safe_filename_piece_unicode(name, max_len=120) or f"{date}_{hash8}"
    return _ensure_ext(name, ext)


def build_content_disposition(filename: str, *, default: str = "download.docx") -> str:
    """
    產生 RFC 5987 的 Content-Disposition：
      attachment; filename="ascii-fallback.docx"; filename*=UTF-8''%E4%B8%AD%E6%96%87.docx

    目標：
    - Starlette header 必須是 latin-1 可編碼 → filename= 只能用 ASCII fallback
    - 但瀏覽器顯示中文要靠 filename*=UTF-8''...
    """
    if not isinstance(filename, str) or not filename.strip():
        filename = default

    # 原始檔名保留（可含中文），但確保沒有奇怪控制字元
    filename = _strip_controls(filename).strip()
    if not filename:
        filename = default

    # ASCII fallback（保證 header 不炸）
    fallback_ascii = _ascii_filename_fallback(filename, default=default)

    # RFC5987：只輸出 ASCII（%xx）
    encoded = quote(filename, safe="")

    return f'attachment; filename="{fallback_ascii}"; filename*=UTF-8\'\'{encoded}'


# ----------------------------
# Internal helpers
# ----------------------------

_WINDOWS_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_MULTI_SPACE_RE = re.compile(r"\s+")
_ASCII_SAFE_RE = re.compile(r"[^0-9A-Za-z._-]+")


def _safe_filename_piece_unicode(s: str, *, max_len: int) -> str:
    """
    保留中文，但移除 Windows 非法字元與控制字元；空白壓底線；裁切長度。
    """
    if not isinstance(s, str):
        s = str(s or "")
    s = s.strip()
    if not s:
        return ""

    s = _strip_controls(s)
    s = _WINDOWS_ILLEGAL_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub("_", s).strip("_")

    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s


def _strip_controls(s: str) -> str:
    # 移除不可見控制字元（保守處理）
    return "".join(ch for ch in s if ch >= " " and ch != "\x7f")


def _ensure_ext(name: str, ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    if not name.lower().endswith(ext.lower()):
        return f"{name}{ext}"
    return name


def _ascii_filename_fallback(filename: str, *, default: str) -> str:
    """
    ASCII fallback：只留 [A-Za-z0-9._-]
    """
    if not isinstance(filename, str):
        return default

    s = _strip_controls(filename).strip()

    # 先丟掉非 ASCII
    s = s.encode("ascii", "ignore").decode("ascii").strip()

    # 再把不安全字元換底線
    s = _ASCII_SAFE_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("._-")

    if not s:
        s = default

    return s


def _get_user_question(pres: object) -> str:
    # pres.user_question
    q = getattr(pres, "user_question", None)
    return q if isinstance(q, str) else ""


def _get_core_terms(pres: object, *, max_core_terms: int) -> list[str]:
    """
    優先：pres.da_section.core_terms（最多 max_core_terms）
    """
    da = getattr(pres, "da_section", None)
    if not da:
        return []
    core_terms = getattr(da, "core_terms", None)
    if not isinstance(core_terms, list):
        return []
    out: list[str] = []
    for t in core_terms:
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
        if len(out) >= max_core_terms:
            break
    return out
