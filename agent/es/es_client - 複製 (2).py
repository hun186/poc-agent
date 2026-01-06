# agent/es/es_client.py
import os
from typing import Any, Dict, Optional, Union, List
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, BadRequestError
from agent.config.index_loader import INDEX_CONFIG

load_dotenv()  # ✅ 讓 CLI / 任何入口都能讀到 .env

IndexType = Union[str, List[str]]

# ===== 1) index 設定整合 =====
_default_idx_from_cfg = INDEX_CONFIG.get("default_index", "news_test")
ES_INDEX_RAW = os.getenv("ES_INDEX", _default_idx_from_cfg)
ES_INDEXES_ENV = [idx.strip() for idx in ES_INDEX_RAW.split(",") if idx.strip()]

topic_map = INDEX_CONFIG.get("topic_index_map", {}) or {}
cfg_indexes: List[str] = []
for cfg in topic_map.values():
    for idx in cfg.get("indexes") or []:
        if idx and idx not in cfg_indexes:
            cfg_indexes.append(idx)

ALL_INDEXES: List[str] = []
for idx in ES_INDEXES_ENV + cfg_indexes:
    if idx and idx not in ALL_INDEXES:
        ALL_INDEXES.append(idx)

ES_INDEX_DEFAULT: str = ES_INDEXES_ENV[0] if ES_INDEXES_ENV else _default_idx_from_cfg

# ===== 2) Elasticsearch 連線 =====
ES_URL = os.getenv("ES_URL")
ES_USERNAME = os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ES_PASSWORD")
ES_TIMEOUT = int(os.getenv("ES_TIMEOUT", "30"))

# ✅ CA_CERT 建議用「絕對路徑」避免工作目錄不同導致找不到
_HERE = os.path.dirname(os.path.abspath(__file__))              # .../agent/es
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..")) # .../poc-agent
CA_CERT = os.path.join(_PROJECT_ROOT, "agent", "certs", "http_ca.crt")

ES = Elasticsearch(
    ES_URL,
    ca_certs=CA_CERT if os.path.exists(CA_CERT) else None,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    ssl_assert_hostname=False,
    request_timeout=ES_TIMEOUT,
)

# ✅ 改成「可控輸出」，避免每次 import 都噴
if os.getenv("ES_CLIENT_VERBOSE", "0") == "1":
    print("[es_client] Connecting to ES...")
    try:
        print(ES.info())
    except Exception as e:
        print("[es_client] ES.info() failed:", e)
    print("[es_client] ALL_INDEXES =", ALL_INDEXES)
    print("[es_client] ES_INDEX_DEFAULT =", ES_INDEX_DEFAULT)


def get_es() -> Elasticsearch:
    """給 CLI / 工具共用的入口（避免外部直接依賴 ES 變數）。"""
    return ES


def resolve_index(hint: Optional[Union[str, List[str]]]) -> IndexType:
    if hint is None:
        return ES_INDEX_DEFAULT

    if isinstance(hint, list):
        idx_list = [str(i).strip() for i in hint if i and str(i).strip()]
        return idx_list[0] if len(idx_list) == 1 else (idx_list or ES_INDEX_DEFAULT)

    raw = str(hint).strip()
    if not raw:
        return ES_INDEX_DEFAULT

    if "," in raw:
        idx_list = [i.strip() for i in raw.split(",") if i.strip()]
        return idx_list[0] if len(idx_list) == 1 else (idx_list or ES_INDEX_DEFAULT)

    return raw


def safe_search(
    body: Dict[str, Any],
    *,
    index: Optional[IndexType] = None,
    allow_highlight_retry: bool = True,
):
    idx = index or ES_INDEX_DEFAULT
    if not idx:
        raise RuntimeError("ES_INDEX_DEFAULT 未設定，請在 .env 設定 ES_INDEX，例如 ES_INDEX=news_test")

    es_index = ",".join(idx) if isinstance(idx, list) else idx

    try:
        return ES.search(
            index=es_index,
            body=body,
            request_timeout=ES_TIMEOUT,
            params={"error_trace": "true"},
        )
    except BadRequestError as e:
        info = str(getattr(e, "info", e))
        if allow_highlight_retry and ("max_analyzed_offset" in info or "highlight" in info):
            body2 = dict(body)
            body2.pop("highlight", None)
            return ES.search(
                index=es_index,
                body=body2,
                request_timeout=ES_TIMEOUT,
                params={"error_trace": "true"},
            )
        raise
