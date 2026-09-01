# api/routers/export.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from fastapi.responses import Response

from api.services.export_word_service import ExportWordService
from shared.http.download_filename import build_content_disposition
from api.services.api_state_store import API_STORE
from api.routers.chat_support import ChatPayload
from api.services.turn_execution import execute_agent_turn

router = APIRouter()

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocxResponse(Response):
    media_type = DOCX_MIME


class ReportWordPayload(ChatPayload):
    """A synchronous Agent request whose representation is a DOCX file."""

    stream: bool = Field(default=False)
    filename: str | None = Field(default=None, max_length=180)


@router.post(
    "/v1/report/word",
    response_class=DocxResponse,
    responses={
        200: {
            "description": "本輪 Agent 產生的 Word 報告",
            "content": {
                DOCX_MIME: {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        }
    },
)
def create_report_word(payload: ReportWordPayload, request: Request):
    if payload.stream:
        raise HTTPException(status_code=422, detail="Word report endpoint does not support streaming")

    try:
        turn = execute_agent_turn(payload=payload, request=request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="後端分析發生錯誤，請稍後再試") from exc

    data, filename = ExportWordService().build_docx_bytes(
        turn.output,
        filename=payload.filename or "agent_output.docx",
    )
    headers = {
        "Content-Disposition": build_content_disposition(filename),
        "Content-Length": str(len(data)),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "X-Session-Id": turn.session_id,
        "X-Turn-Id": turn.turn_id,
        "X-Request-Id": turn.request_id,
    }
    return DocxResponse(data, headers=headers)

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
):
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
