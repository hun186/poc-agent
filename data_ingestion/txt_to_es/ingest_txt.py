# data_ingestion/txt_to_es/ingest_txt.py
#cd /d D:\shared\TopicClassification\poc-agent
#python -m data_ingestion.txt_to_es.ingest_txt -d "D:\shared\TopicClassification\poc-agent\data\軍事情報文本\mil_30k_300days"
#python -m data_ingestion.txt_to_es.ingest_txt -d "D:\shared\TopicClassification\TopicTextCrawler\Books\新聞網\聯合國新聞網\UnTagged\最新消息" -i news_test
#python -m data_ingestion.txt_to_es.ingest_txt -d "D:\shared\TopicClassification\poc-agent\data\資料庫條目測試" -i srp_test

#跨路徑去重：
#python -m data_ingestion.txt_to_es.ingest_txt -d "D:\path\to\txt_dir" --dedup-by-content

#如果想看 es_client 的連線資訊（平常不要吵）：
#set ES_CLIENT_VERBOSE=1
#python -m data_ingestion.txt_to_es.ingest_txt -d "D:\path\to\txt_dir"

from __future__ import annotations

import os
import argparse
import hashlib
from datetime import datetime
from typing import Dict, Generator, Iterable, List, Tuple

from elasticsearch import helpers
from dotenv import load_dotenv

from agent.es.es_client import get_es, ES_INDEX_DEFAULT
from agent.es.reference_text import add_reference_text_mapping, set_ingested_text


INDEX_MAPPINGS: Dict = {
    "properties": {
        "uuid": {"type": "keyword"},
        "rawInfo": {"properties": {"content": {"type": "text"}, "langCode": {"type": "keyword"}}},
        "communication": {"properties": {"subject": {"type": "text"}}},
        "itc": {"properties": {"rawTypeCode": {"type": "keyword"}}},
        "importDT": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
        "userNames": {"type": "keyword"},
        "selectedMessage": {"type": "boolean"},
        "ak6": {"properties": {"select": {"properties": {"selectorName": {"type": "keyword"}}}}},
        "ai": {"properties": {"classLabels": {"properties": {"highValue": {"type": "boolean"}}}}},
        "sourceFile": {
            "properties": {
                "path": {"type": "keyword"},
                "size": {"type": "long"},
                "mtime": {"type": "long"},
                "dedupByContent": {"type": "boolean"},
            }
        },
    }
}


def build_index_mappings() -> Dict:
    """Build mappings using the current agent reference-text field contract."""
    return add_reference_text_mapping(INDEX_MAPPINGS)


def iter_txt_paths(root_dir: str, exts: Tuple[str, ...] = (".txt",)) -> Generator[str, None, None]:
    exts = tuple(e.lower() for e in exts)
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                yield os.path.abspath(os.path.join(dirpath, fn))


def read_text_best_effort(path: str) -> str:
    candidates = ["utf-8-sig", "utf-8", "cp950", "big5", "latin-1"]
    for enc in candidates:
        try:
            with open(path, "r", encoding=enc, errors="strict") as fp:
                return fp.read()
        except Exception:
            pass
    with open(path, "r", encoding="utf-8", errors="ignore") as fp:
        return fp.read()


def make_uuid_from_file(path: str) -> str:
    try:
        st = os.stat(path)
        basis = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        basis = os.path.abspath(path)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def make_uuid_from_content(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_doc_from_file(
    path: str,
    lang_code: str = "C",
    user_name: str = "crawler",
    raw_type_code: str = "05",
    dedup_by_content: bool = False,
):
    content = read_text_best_effort(path)
    subject = os.path.splitext(os.path.basename(path))[0]
    doc_id = make_uuid_from_content(path) if dedup_by_content else make_uuid_from_file(path)

    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    try:
        st = os.stat(path)
        file_size = st.st_size
        file_mtime = int(st.st_mtime)
    except Exception:
        file_size = None
        file_mtime = None

    source = {
        "uuid": doc_id,
        "rawInfo": {"langCode": lang_code},
        "communication": {"subject": subject},
        "itc": {"rawTypeCode": raw_type_code},
        "importDT": now_iso,
        "userNames": user_name,
        "selectedMessage": False,
        "ak6": {"select": {"selectorName": "Crawler"}},
        "ai": {"classLabels": {"highValue": False}},
        "sourceFile": {
            "path": os.path.abspath(path),
            "size": file_size,
            "mtime": file_mtime,
            "dedupByContent": dedup_by_content,
        },
    }
    set_ingested_text(source, content)
    return doc_id, source


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
        es.indices.create(index=index_name, body={"mappings": build_index_mappings()})
        print(f"✅ Created index: {index_name}")
    else:
        print(f"ℹ️ Index already exists: {index_name}")


def bulk_insert_txt_dir(
    index_name: str,
    root_dir: str,
    batch_size: int = 500,
    lang_code: str = "C",
    user_name: str = "crawler",
    op_type: str = "index",
    dedup_by_content: bool = False,
) -> int:
    es = get_es()
    ensure_index(es, index_name=index_name)

    def gen_actions():
        for p in iter_txt_paths(root_dir):
            doc_id, src = build_doc_from_file(
                p,
                lang_code=lang_code,
                user_name=user_name,
                dedup_by_content=dedup_by_content,
            )
            yield {"_op_type": op_type, "_index": index_name, "_id": doc_id, "_source": src}

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
                    op, info = next(iter(e.items()))
                    status = info.get("status")
                    if status == 409:
                        dup += 1
                    else:
                        fail += 1
    
            total_success += success
            total_dup += dup
            total_fail += fail
            # dup 主要會在 --op create 時出現（已存在 -> 409）
            print(f"✅ 批次完成：成功 {success} 筆，跳過(已存在) {dup} 筆，失敗 {fail} 筆，累計成功 {total_success} 筆")
    
        except Exception as e:
            print(f"⚠️ 批次寫入失敗：{e}")
    verb = "新增" if op_type == "create" else "寫入/覆寫"
    print(f"🎯 全部完成：成功{verb} {total_success} 筆，跳過(已存在) {total_dup} 筆，失敗 {total_fail} 筆")
    #print(f"🎯 全部完成，成功寫入/覆寫：{total_success} 筆")
    return total_success,total_dup,total_fail


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="遞迴掃描資料夾中的 .txt 並 bulk 寫入 ES（共用 agent.es.es_client）")
    parser.add_argument("-d", "--dir", required=True, help="要遞迴掃描的根目錄")
    parser.add_argument("-i", "--index", default="", help="索引名稱（不填則用 .env 的 ES_INDEX）")
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--lang", default="C")
    parser.add_argument("--user", default="crawler")
    parser.add_argument(
        "--op",
        choices=["index", "create"],
        default="create",
        help="create=只新增不存在的 doc，已存在則跳過；index=新增或覆寫既有 doc，可能清掉分析結果",
    )
    parser.add_argument("--yes", action="store_true", help="略過危險操作確認")
    parser.add_argument("--dedup-by-content", action="store_true")

    args = parser.parse_args()

    if args.op == "index" and not args.yes:
        print("⚠️ 你選擇了 --op index，這會覆寫已存在的 ES doc。")
        print("⚠️ 若 doc 已經做過分類、摘要、標註或其他分析，可能會被還原成原始未分析狀態。")
        confirm = input("請輸入 YES 才繼續覆寫：").strip()
    
        if confirm != "YES":
            print("❌ 已取消匯入。若只是想跳過已存在資料，請使用預設 create 模式。")
            return
        
    index_name = (args.index or os.getenv("ES_INDEX") or ES_INDEX_DEFAULT).strip()
    if not index_name:
        raise RuntimeError("未指定 index：請用 -i 指定，或在 .env 設定 ES_INDEX")

    bulk_insert_txt_dir(
        index_name=index_name,
        root_dir=args.dir,
        batch_size=args.batch,
        lang_code=args.lang,
        user_name=args.user,
        op_type=args.op,
        dedup_by_content=args.dedup_by_content,
    )


if __name__ == "__main__":
    main()
