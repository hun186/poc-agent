# api/routers/export.py
from __future__ import annotations
#import re
#from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from api.services.sessions import get_last_structured
from api.services.export_word_service import ExportWordService
from shared.http.download_filename import build_content_disposition

router = APIRouter()

'''
def _ascii_filename_fallback(filename: str, *, default: str = "agent_output.docx") -> str:
    """
    把檔名清成純 ASCII，避免 header encode 爆炸。
    """
    if not isinstance(filename, str) or not filename.strip():
        return default

    # 先粗暴丟掉非 ASCII
    s = filename.encode("ascii", "ignore").decode("ascii")
    s = s.strip()

    # 再把奇怪字元換底線
    s = re.sub(r'[^A-Za-z0-9._-]+', "_", s).strip("._-")
    if not s:
        s = default

    if not s.lower().endswith(".docx"):
        s += ".docx"
    return s


def build_content_disposition(filename: str) -> str:
    """
    RFC 5987：同時提供
      - filename="ascii-fallback.docx"
      - filename*=UTF-8''%E4%B8%AD%E6%96%87.docx
    讓 Chrome/Edge 能正確顯示中文檔名，又不會讓 Starlette header encode 爆炸。
    """
    if not filename:
        filename = "agent_output.docx"
    if not filename.lower().endswith(".docx"):
        filename += ".docx"

    fallback = _ascii_filename_fallback(filename)
    encoded = quote(filename, safe="")  # 只輸出 ASCII（%xx）
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
'''

@router.get("/v1/export/word")
def export_word(session_id: str = Query(..., description="會話 session_id")):
    """
    依 session_id 取出上一輪 structured out，轉成美觀的 Word 檔。
    """
    last_structured = get_last_structured()
    out = last_structured.get(session_id)

    if not isinstance(out, dict):
        raise HTTPException(status_code=404, detail="找不到可匯出的報告內容（可能尚未產生結構化輸出）。")

    svc = ExportWordService()
    data, filename = svc.build_docx_bytes(out, filename="agent_output.docx")
    cd = build_content_disposition(filename)
    
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": cd,
            "Cache-Control": "no-store",
        },
    )
