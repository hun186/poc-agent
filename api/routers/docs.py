# api/routers/docs.py
import re
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from elasticsearch import NotFoundError
from api.core.settings import ES, ALL_INDEXES

router = APIRouter()

def _get_doc_source_or_404(doc_id: str) -> dict:
    """
    共用：依 doc_id（可能是 _id 或 uuid）從多個 index 中找到一筆文件的 _source。
    找不到就丟 404。
    """
    # 1) 逐一嘗試用 _id 直接抓（每個 index 都試）
    print("ALL_INDEXES",ALL_INDEXES)
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

    # 4) 最後保底：wildcard 模糊比對
    res = ES.search(
        index=ALL_INDEXES,
        body={
            "size": 1,
            "_source": True,
            "query": {"wildcard": {"uuid": {"value": f"*{doc_id}*"}}},
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

@router.get("/v1/docs/{doc_id}")
def get_doc(doc_id: str):
    return _get_doc_source_or_404(doc_id)
@router.get("/v1/docs/{doc_id}/fulltext")
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

    # ==== 1) 全文 ====
    full_text = (
        src.get("full_text")
        or (src.get("rawInfo") or {}).get("content")
        or src.get("content")
        or ""
    )

    if not isinstance(full_text, str) or not full_text.strip():
        raise HTTPException(status_code=404, detail="文件存在，但沒有可用的全文內容。")

    # ==== 2) 標題 ====
    md = src.get("multidim_event_json") or {}
    comm = src.get("communication") or {}

    title = (
        md.get("article_title")
        or comm.get("subject")
        or src.get("title")
        or (src.get("rawInfo") or {}).get("title")
        or doc_id
    )

    # ==== 3) 日期：優先用 Event.time_iso，再用 Event_Timeline 的最大 date_iso ====
    def infer_article_date(src_doc: dict) -> str | None:
        mdj = src_doc.get("multidim_event_json") or {}

        evt = mdj.get("Event") or {}
        if isinstance(evt, dict):
            time_iso = evt.get("time_iso")
            if isinstance(time_iso, str) and time_iso.strip():
                return time_iso.strip()

        tl = mdj.get("Event_Timeline") or []
        dates: list[str] = []
        for item in tl:
            if not isinstance(item, dict):
                continue
            di = item.get("date_iso")
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
            }
        )

    # === TXT 模式：單純吐出全文（可選擇是否附件下載） ===
    if format.lower() == "txt":
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
            filename_ascii = f"{safe_date}_{ascii_title}_{safe_uuid}.txt"
            filename_utf8  = f"{safe_date}_{utf8_title}_{safe_uuid}.txt"
    
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