# api/routers/export.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.responses import StreamingResponse

from api.services.export_word_service import ExportWordService
from shared.http.download_filename import build_content_disposition
from api.services.api_state_store import API_STORE
from api.routers.editor_dependencies import current_user, scope_resource_id
from api.services.auth_store import AuthUser

router = APIRouter()

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def _load_out_from_disk(session_id: str, turn_id: str | None) -> dict | None:
    raw = API_STORE.read_raw()  # ✅ 每次都讀最新檔
    if not isinstance(raw, dict):
        return None

    if turn_id:
        hist = raw.get("structured_history") or {}
        turns = hist.get(session_id) or {}
        out = turns.get(str(turn_id))
        return out if isinstance(out, dict) else None

    # turn_id 沒給 → 相容舊行為：拿最新一輪
    last = raw.get("last_structured") or {}
    out = last.get(session_id)
    return out if isinstance(out, dict) else None



@router.get("/v1/export/word")
def export_word(
    session_id: str = Query(..., description="會話 session_id"),
    turn_id: str | None = Query(None, description="該輪 turn_id（建議使用 request_id）"),
    user: AuthUser = Depends(current_user),
):
    session_id = scope_resource_id(user, session_id)
    raw = API_STORE.read_raw() or {}
    last = raw.get("last_structured") or {}
    hist = raw.get("structured_history") or {}

    out = None
    if turn_id:
        out = (hist.get(session_id) or {}).get(str(turn_id))
    else:
        out = last.get(session_id)

    if not isinstance(out, dict):
        raise HTTPException(
            status_code=404,
            detail="找不到可匯出的報告內容（該輪可能尚未保存、已被淘汰，或 turn_id 不正確）。",
        )

    svc = ExportWordService()
    data, filename = svc.build_docx_bytes(out, filename="agent_output.docx")
    cd = build_content_disposition(filename)

    headers = {
        "Content-Disposition": cd,
        "Content-Length": str(len(data)),          # 2) 明確長度
        "X-Content-Type-Options": "nosniff",       # 2) 禁止嗅探
        "Cache-Control": "no-store",
    }
    
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        #headers={"Content-Disposition": cd, "Cache-Control": "no-store"},
        headers=headers,
    )
