# api/routers/export.py
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from api.services.sessions import get_last_structured
from api.services.export_word_service import ExportWordService

router = APIRouter()

        
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
    
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
