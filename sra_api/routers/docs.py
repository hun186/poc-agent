# api/routers/docs.py
import re
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from elasticsearch import NotFoundError
#from api.core.settings import ES, ALL_INDEXES
#from agent.es.es_client import ES, ALL_INDEXES

from agent.es.es_client import get_es, init_index_cache, ALL_INDEXES
from agent.es.evidence_core.json_utils import as_blocks, json_load_maybe
from agent.es.reference_text import (
    DEFAULT_REFERENCE_TEXT_FIELD,
    get_reference_text,
    get_reference_text_field,
)
from api.security.models import AuthPrincipal
from api.security.principal import optional_principal, require_principal_or_capability
from api.security.scopes import DOCUMENT_READ

router = APIRouter()

def _get_doc_source_or_404(doc_id: str) -> dict:
    """
    共用：依 doc_id（可能是 _id 或 uuid）從多個 index 中找到一筆文件的 _source。
    找不到就丟 404。
    """
    # ✅ 確保 index 清單已可用（且最好是 ES 存在的）
    init_index_cache(live_check=True)
    ES = get_es()
    print("ALL_INDEXES",ALL_INDEXES)
    
    # 1) 逐一嘗試用 _id 直接抓（每個 index 都試）
    for idx in ALL_INDEXES:
        try:
            got = ES.get(index=idx, id=doc_id, _source=True)
            src = got.get("_source", {}) or {}
            src["_id"] = got.get("_id")
            src["_index"] = got.get("_index")
            return src
        except NotFoundError:
            continue
        except Exception:
            # 其他錯誤先忽略，稍後用 search fallback
            continue

    # 2) 用 uuid.keyword 精確比對（跨索引 search）
    res = ES.search(
        index=ALL_INDEXES,
        body={
            "size": 1,
            "_source": True,
            "query": {"term": {"uuid.keyword": doc_id}},
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {}) or {}
        src["_id"] = hit.get("_id")
        src["_index"] = hit.get("_index")
        return src

    # 3) 再試一次 uuid（非 keyword 的情況）
    res = ES.search(
        index=ALL_INDEXES,
        body={
            "size": 1,
            "_source": True,
            "query": {"term": {"uuid": doc_id}},
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {}) or {}
        src["_id"] = hit.get("_id")
        src["_index"] = hit.get("_index")
        return src

    raise HTTPException(status_code=404, detail="document not found")

CAPABILITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

@router.get("/v1/docs/{doc_id}")
def get_doc(doc_id: str, request: Request, principal: AuthPrincipal | None = Depends(optional_principal)):
    capability = require_principal_or_capability(
        request, principal, required_scope=DOCUMENT_READ, resource_type="doc_detail",
        binding={"doc_id": doc_id}, allowed_query_keys=set(),
    )
    return JSONResponse(_get_doc_source_or_404(doc_id), headers=CAPABILITY_HEADERS if capability else None)
def get_fulltext_on_demand(
    doc_id: str,
    format: str = Query(
        "json",
        description="回傳格式：json 或 txt，預設 json。",
    ),
    download: bool = Query(
        False,
        description="在 format=txt 時，為 true 則以附件下載形式回傳。",
    ),
    text_layer: Annotated[
        Literal["reference", "raw", "both"],
        Query(description="文本層次：代理人參考文本、原始未處理文本，或兩者。"),
    ] = "reference",
):
    """
    按需下載全文：
    - 不經過 LLM / 文件跟進代理人。
    - 直接用既有 /v1/docs 的查詢邏輯找到文件，抽出全文欄位回傳。
    """
    src = _get_doc_source_or_404(doc_id)

    # 如果 _get_doc_source_or_404 回傳的是整個 ES hit，先把 _source 拉出來
    if isinstance(src, dict) and "_source" in src:
        src = src["_source"]

    # ==== 1) 多層次文本 ====
    reference_field = get_reference_text_field()
    if reference_field == DEFAULT_REFERENCE_TEXT_FIELD:
        reference_text = src.get("full_text") or get_reference_text(src) or src.get("content") or ""
    else:
        reference_text = get_reference_text(src, field=reference_field)
    raw_text = get_reference_text(src, field=DEFAULT_REFERENCE_TEXT_FIELD)

    layer_payloads = {
        "reference": {
            "label": "代理人參考文本",
            "field": reference_field,
            "text": reference_text,
            "total_length": len(reference_text),
            "available": bool(reference_text),
        },
        "raw": {
            "label": "原始未處理文本",
            "field": DEFAULT_REFERENCE_TEXT_FIELD,
            "text": raw_text,
            "total_length": len(raw_text),
            "available": bool(raw_text),
        },
    }
    available_text_layers = {
        name: {
            "label": item["label"],
            "field": item["field"],
            "available": item["available"],
            "total_length": item["total_length"],
        }
        for name, item in layer_payloads.items()
    }

    if text_layer == "both":
        full_text = reference_text or raw_text
        if not full_text:
            raise HTTPException(status_code=404, detail="文件存在，但沒有可用的文本內容。")
    else:
        full_text = layer_payloads[text_layer]["text"]
        if not full_text:
            label = layer_payloads[text_layer]["label"]
            raise HTTPException(status_code=404, detail=f"文件存在，但沒有可用的{label}。")

    # ==== 2) 標題 ====
    md_blocks = as_blocks(src.get("multidim_event_json"))
    md = md_blocks[0] if md_blocks else {}
    comm = src.get("communication") or {}

    title = (
        md.get("article_title")
        or comm.get("subject")
        or src.get("title")
        or (src.get("rawInfo") or {}).get("title")
        or doc_id
    )

    # ==== 3) 日期：優先用 Event.time_iso，再用 Event_Timeline 的最大 time_iso ====
    def infer_article_date(src_doc: dict) -> str | None:
        mdj_blocks = as_blocks(src_doc.get("multidim_event_json") if isinstance(src_doc, dict) else None)
        dates: list[str] = []
        for mdj in mdj_blocks:
            events = json_load_maybe(mdj.get("Event") or [])
            if isinstance(events, dict):
                events = [events]
            if not isinstance(events, list):
                events = []
            for evt in events:
                if not isinstance(evt, dict):
                    continue
                time_iso = evt.get("time_iso")
                if isinstance(time_iso, str) and time_iso.strip():
                    return time_iso.strip()

            tl = json_load_maybe(mdj.get("Event_Timeline") or [])
            if isinstance(tl, dict):
                tl = [tl]
            if not isinstance(tl, list):
                tl = []
            for item in tl:
                if not isinstance(item, dict):
                    continue
                # date_iso is retained only for documents written before the
                # nested timeline migration; new documents use time_iso.
                di = item.get("time_iso") or item.get("date_iso")
                if isinstance(di, str) and di.strip():
                    dates.append(di.strip())
        if dates:
            return max(dates)
        return None

    date = (
        md.get("article_date_iso")
        or infer_article_date(src)
        or (src.get("rawInfo") or {}).get("date")
        or None
    )

    # ==== 4) 主旨（subject）====
    subject = (
        comm.get("subject")
        or md.get("article_title")
        or src.get("subject")
        or (src.get("rawInfo") or {}).get("subject")
        or None
    )

    total_length = len(full_text)

    # === JSON 模式：meta + full_text 一起回 ===
    fmt = (format or "").lower()
    if fmt == "json":
        return JSONResponse(
            {
                "uuid": src.get("uuid", doc_id),
                "title": title,
                "date": date,
                "subject": subject,
                "total_length": total_length,
                "full_text": full_text,
                "text_layer": text_layer,
                "text_field": reference_field if text_layer == "both" else layer_payloads[text_layer]["field"],
                "available_text_layers": available_text_layers,
                **({"text_layers": layer_payloads} if text_layer == "both" else {}),
            }
        )

    # === TXT 模式：單純吐出全文（可選擇是否附件下載） ===
    if format.lower() == "txt":
        if text_layer == "both":
            sections = []
            for name in ("reference", "raw"):
                item = layer_payloads[name]
                if item["available"]:
                    sections.append(
                        f"===== {item['label']} ({item['field']}) =====\n\n{item['text']}"
                    )
            full_text = "\n\n".join(sections)
        headers = {}
    
        if download:
            from urllib.parse import quote
    
            # ===== 1) 日期（放最前面）=====
            safe_date = (date or "unknown-date").replace(":", "-").replace("/", "-")
    
            # ===== 2) 標題（中間）=====
            raw_title = str(title).strip() or "no-title"
    
            # 給 filename= 用的 ASCII 版本（舊瀏覽器）
            ascii_title = re.sub(r'[\\/:*?"<>|]+', "_", raw_title)
            ascii_title = re.sub(r"[^\x00-\x7F]+", "_", ascii_title).strip("_")
            if not ascii_title:
                ascii_title = "no-title"
    
            # 給 filename*= 用的 UTF-8 版本（新瀏覽器顯示中文）
            utf8_title = quote(raw_title)
    
            # ===== 3) UUID（放最後）=====
            safe_uuid = src.get("uuid", doc_id)
    
            # ===== 4) 組合檔名 =====
            filename_ascii = f"{safe_date}_{ascii_title}_{safe_uuid}_{text_layer}.txt"
            filename_utf8  = f"{safe_date}_{utf8_title}_{safe_uuid}_{text_layer}.txt"
    
            headers["Content-Disposition"] = (
                f"attachment; "
                f'filename="{filename_ascii}"; '
                f"filename*=UTF-8''{filename_utf8}"
            )
    
        return PlainTextResponse(
            content=full_text,
            headers=headers,
            media_type="text/plain; charset=utf-8",
        )


    raise HTTPException(status_code=400, detail="format 只支援 json 或 txt。")


@router.get("/v1/docs/{doc_id}/fulltext")
def secured_fulltext(
    doc_id: str,
    request: Request,
    format: str = Query("json"),
    download: str = Query("0"),
    text_layer: Literal["reference", "raw", "both"] = Query("reference"),
    principal: AuthPrincipal | None = Depends(optional_principal),
):
    raw_download = request.query_params.getlist("download")
    if len(raw_download) > 1 or (raw_download and raw_download[0] not in {"0", "1"}):
        raise HTTPException(401, "Invalid capability parameters")
    canonical_download = download
    capability = require_principal_or_capability(
        request, principal, required_scope=DOCUMENT_READ, resource_type="doc_fulltext",
        binding={"doc_id": doc_id, "format": format, "download": canonical_download, "text_layer": text_layer},
        allowed_query_keys={"format", "download", "text_layer"},
    )
    response = get_fulltext_on_demand(doc_id, format=format, download=download == "1", text_layer=text_layer)
    if capability:
        response.headers.update(CAPABILITY_HEADERS)
    return response
