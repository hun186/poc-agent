# data_ingestion/sql_to_es/ingest_sql.py
# cd /d D:\shared\TopicClassification\poc-agent
# python -m data_ingestion.sql_to_es.ingest_sql --config config/sql_import/srp_import.json

from __future__ import annotations

import os
import re
import json
import argparse
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Iterable, List, Optional

import pyodbc
from elasticsearch import helpers
from dotenv import load_dotenv

from agent.es.es_client import get_es, ES_INDEX_DEFAULT
from agent.es.ingest_txt import INDEX_MAPPINGS
from data_ingestion.excel_to_sql.sql_utils import detect_odbc_driver


SQL_INDEX_MAPPINGS: Dict = deepcopy(INDEX_MAPPINGS)
SQL_INDEX_MAPPINGS["properties"]["sourceSql"] = {
    "properties": {
        "server": {"type": "keyword"},
        "database": {"type": "keyword"},
        "table": {"type": "keyword"},
        "idColumn": {"type": "keyword"},
        "idValue": {"type": "keyword"},
        "contentColumn": {"type": "keyword"},
        "titleColumn": {"type": "keyword"},
        "rowDTColumn": {"type": "keyword"},
        "rowDT": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
        "dedupByContent": {"type": "boolean"},
        "whereClause": {"type": "keyword"}
    }
}


def load_json_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def get_nested(cfg: Dict[str, Any], path: str, default=None):
    cur = cfg
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def require_nested(cfg: Dict[str, Any], path: str):
    val = get_nested(cfg, path, default=None)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise ValueError(f"設定檔缺少必要欄位：{path}")
    return val


def chunked(iterable: Iterable, size: int) -> Generator[List, None, None]:
    buf: List = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def ensure_index(es, index_name: str):
    if not es.indices.exists(index=index_name):
        es.indices.create(index=index_name, body={"mappings": SQL_INDEX_MAPPINGS})
        print(f"✅ Created index: {index_name}")
    else:
        print(f"ℹ️ Index already exists: {index_name}")


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def to_iso_utc(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(microsecond=0).isoformat() + "Z"
        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    text = str(value).strip()
    return text or None


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def derive_title(content: str, max_len: int = 120) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    if not text:
        return "(empty)"
    return text[:max_len]


def quote_ident(name: str) -> str:
    if not name:
        raise ValueError("欄位名稱不可為空")
    return f"[{name.replace(']', ']]')}]"


def quote_object_path(name: str) -> str:
    parts = [p.strip() for p in name.split(".") if p.strip()]
    if not parts:
        raise ValueError(f"無效物件名稱: {name}")
    return ".".join(quote_ident(p) for p in parts)


def build_conn_str_from_config(cfg: Dict[str, Any]) -> str:
    driver = detect_odbc_driver(get_nested(cfg, "db.driver", "auto"))
    server = require_nested(cfg, "db.server")
    database = require_nested(cfg, "db.database")
    trusted_connection = bool(get_nested(cfg, "db.trusted_connection", False))
    user = get_nested(cfg, "db.user", "")
    password = get_nested(cfg, "db.password", "")
    encrypt = bool(get_nested(cfg, "db.encrypt", False))
    trust_cert = bool(get_nested(cfg, "db.trust_server_certificate", False))

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}"
    ]

    if trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        if not user:
            raise ValueError("設定檔缺少 db.user")
        if not password:
            raise ValueError("設定檔缺少 db.password")
        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")

    if encrypt:
        parts.append("Encrypt=yes")
    if trust_cert:
        parts.append("TrustServerCertificate=yes")

    return ";".join(parts)


def build_select_sql_from_config(cfg: Dict[str, Any]) -> str:
    table = require_nested(cfg, "source.table")
    content_col = require_nested(cfg, "source.columns.content")
    id_col = get_nested(cfg, "source.columns.id", "") or ""
    title_col = get_nested(cfg, "source.columns.title", "") or ""
    row_dt_col = get_nested(cfg, "source.columns.row_dt", "") or ""
    where_clause = get_nested(cfg, "source.query.where", "") or ""
    order_by = get_nested(cfg, "source.query.order_by", "") or ""
    top = int(get_nested(cfg, "source.query.top", 0) or 0)

    select_cols = []

    if id_col:
        select_cols.append(f"{quote_ident(id_col)} AS [__id]")

    select_cols.append(f"{quote_ident(content_col)} AS [__content]")

    if title_col:
        select_cols.append(f"{quote_ident(title_col)} AS [__title]")

    if row_dt_col:
        select_cols.append(f"{quote_ident(row_dt_col)} AS [__rowdt]")

    top_sql = f"TOP {top} " if top > 0 else ""
    sql = f"SELECT {top_sql}{', '.join(select_cols)} FROM {quote_object_path(table)}"

    where_parts = [
        f"{quote_ident(content_col)} IS NOT NULL",
        f"LEN(LTRIM(RTRIM(CAST({quote_ident(content_col)} AS NVARCHAR(MAX))))) > 0"
    ]

    if where_clause:
        where_parts.append(f"({where_clause})")

    sql += " WHERE " + " AND ".join(where_parts)

    if order_by:
        sql += f" ORDER BY {order_by}"
    elif id_col:
        sql += f" ORDER BY {quote_ident(id_col)}"

    return sql


def iter_sql_rows(conn_str: str, sql: str, fetch_size: int = 500) -> Generator[Dict[str, Any], None, None]:
    conn = None
    cursor = None
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [col[0] for col in cursor.description]

        while True:
            rows = cursor.fetchmany(fetch_size)
            if not rows:
                break
            for row in rows:
                yield dict(zip(columns, row))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def make_doc_id(
    *,
    server: str,
    database: str,
    table: str,
    id_col: str,
    row_id: Any,
    title: str,
    content: str,
    dedup_by_content: bool,
) -> str:
    if dedup_by_content:
        basis = content
    elif id_col and row_id is not None:
        basis = f"{server}|{database}|{table}|{id_col}|{row_id}"
    else:
        basis = f"{server}|{database}|{table}|{title}|{content}"

    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()


def build_doc_from_row(row: Dict[str, Any], cfg: Dict[str, Any]):
    server = require_nested(cfg, "db.server")
    database = require_nested(cfg, "db.database")
    table = require_nested(cfg, "source.table")

    id_col = get_nested(cfg, "source.columns.id", "") or ""
    title_col = get_nested(cfg, "source.columns.title", "") or ""
    content_col = require_nested(cfg, "source.columns.content")
    row_dt_col = get_nested(cfg, "source.columns.row_dt", "") or ""

    lang_code = get_nested(cfg, "import.lang_code", "C")
    user_name = get_nested(cfg, "import.user_name", "sql_importer")
    dedup_by_content = bool(get_nested(cfg, "import.dedup_by_content", False))
    selector_name = get_nested(cfg, "import.selector_name", "SQLImport")
    raw_type_code = get_nested(cfg, "import.raw_type_code", "05")
    where_clause = get_nested(cfg, "source.query.where", "") or ""

    content = normalize_text(row.get("__content"))
    if not content.strip():
        return None, None

    title = normalize_text(row.get("__title")) if title_col else ""
    if not title.strip():
        title = derive_title(content)

    row_id = row.get("__id") if id_col else None
    row_dt = to_iso_utc(row.get("__rowdt")) if row_dt_col else None

    doc_id = make_doc_id(
        server=server,
        database=database,
        table=table,
        id_col=id_col,
        row_id=row_id,
        title=title,
        content=content,
        dedup_by_content=dedup_by_content,
    )

    source = {
        "uuid": doc_id,
        "rawInfo": {
            "content": content,
            "langCode": lang_code
        },
        "communication": {
            "subject": title
        },
        "itc": {
            "rawTypeCode": raw_type_code
        },
        "importDT": utc_now_iso(),
        "userNames": user_name,
        "selectedMessage": False,
        "ak6": {
            "select": {
                "selectorName": selector_name
            }
        },
        "ai": {
            "classLabels": {
                "highValue": False
            }
        },
        "sourceSql": {
            "server": server,
            "database": database,
            "table": table,
            "idColumn": id_col or None,
            "idValue": None if row_id is None else str(row_id),
            "contentColumn": content_col,
            "titleColumn": title_col or None,
            "rowDTColumn": row_dt_col or None,
            "rowDT": row_dt,
            "dedupByContent": dedup_by_content,
            "whereClause": where_clause or None
        }
    }

    return doc_id, source


def bulk_insert_sql_from_config(cfg: Dict[str, Any]) -> tuple[int, int, int, int]:
    es = get_es()

    index_name = (get_nested(cfg, "index_name", "") or os.getenv("ES_INDEX") or ES_INDEX_DEFAULT).strip()
    if not index_name:
        raise RuntimeError("未指定 index_name，且 .env 也沒有 ES_INDEX")

    batch_size = int(get_nested(cfg, "import.batch_size", 500) or 500)
    op_type = get_nested(cfg, "import.op_type", "index")

    ensure_index(es, index_name=index_name)

    conn_str = build_conn_str_from_config(cfg)
    sql = build_select_sql_from_config(cfg)

    print(f"ℹ️ SQL: {sql}")

    stats = {"skip_empty": 0}

    def gen_actions():
        for row in iter_sql_rows(conn_str=conn_str, sql=sql, fetch_size=batch_size):
            doc_id, src = build_doc_from_row(row, cfg)
            if not doc_id or not src:
                stats["skip_empty"] += 1
                continue

            yield {
                "_op_type": op_type,
                "_index": index_name,
                "_id": doc_id,
                "_source": src
            }

    total_success = 0
    total_dup = 0
    total_fail = 0

    for batch in chunked(gen_actions(), batch_size):
        try:
            success, errors = helpers.bulk(es, batch, raise_on_error=False)

            dup = 0
            fail = 0

            if errors:
                for e in errors:
                    _, info = next(iter(e.items()))
                    status = info.get("status")
                    if status == 409:
                        dup += 1
                    else:
                        fail += 1

            total_success += success
            total_dup += dup
            total_fail += fail

            print(
                f"✅ 批次完成：成功 {success} 筆，跳過(已存在) {dup} 筆，"
                f"失敗 {fail} 筆，累計成功 {total_success} 筆"
            )

        except Exception as e:
            print(f"⚠️ 批次寫入失敗：{e}")

    verb = "新增" if op_type == "create" else "寫入/覆寫"
    print(
        f"🎯 全部完成：成功{verb} {total_success} 筆，"
        f"跳過(已存在) {total_dup} 筆，失敗 {total_fail} 筆，"
        f"跳過(空內容) {stats['skip_empty']} 筆"
    )

    return total_success, total_dup, total_fail, stats["skip_empty"]


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="依設定檔從 SQL Server 匯入資料到 Elasticsearch")
    parser.add_argument("--config", required=True, help="JSON 設定檔路徑")
    args = parser.parse_args()

    cfg = load_json_config(args.config)
    bulk_insert_sql_from_config(cfg)


if __name__ == "__main__":
    main()