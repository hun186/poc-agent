# agent/es/es_client.py
import os
from typing import Any, Dict, Optional, Union, List
from elasticsearch import Elasticsearch, BadRequestError
from agent.config.index_loader import INDEX_CONFIG

IndexType = Union[str, List[str]]

# ===== 1) index 設定整合 =====

# 從 config 讀預設 index
_default_idx_from_cfg = INDEX_CONFIG.get("default_index", "news_test")

# .env > config
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

# 給舊 code 吃的預設 index
ES_INDEX_DEFAULT: str = ES_INDEXES_ENV[0] if ES_INDEXES_ENV else _default_idx_from_cfg

# ===== 2) Elasticsearch 連線 =====

ES_URL = os.getenv("ES_URL")
ES_USERNAME = os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ES_PASSWORD")
CA_CERT = "agent/certs/http_ca.crt"

ES = Elasticsearch(
    ES_URL,
    ca_certs=CA_CERT,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    ssl_assert_hostname=False,
)

print("[es_client] Connecting to ES...")
print(ES.info())
print("[es_client] ALL_INDEXES =", ALL_INDEXES)
print("[es_client] ES_INDEX_DEFAULT =", ES_INDEX_DEFAULT)


# ===== 3) 共用工具：index 解析 & 安全查詢 =====

def resolve_index(hint: Optional[Union[str, List[str]]]) -> IndexType:
    """
    支援：
    - None           → 用 ES_INDEX_DEFAULT
    - "a"            → 單一 index
    - "a,b,c"        → 多 index
    - ["a","b","c"]  → 多 index
    """
    # --- None ---
    if hint is None:
        print("[resolve_index] no hint → use default:", ES_INDEX_DEFAULT)
        return ES_INDEX_DEFAULT

    # --- list[str] ---
    if isinstance(hint, list):
        idx_list = [str(i).strip() for i in hint if i and str(i).strip()]

        if not idx_list:
            print("[resolve_index] empty list → use default:", ES_INDEX_DEFAULT)
            return ES_INDEX_DEFAULT

        if len(idx_list) == 1:
            print("[resolve_index] single-item list →", idx_list[0])
            return idx_list[0]

        print("[resolve_index] list index →", idx_list)
        return idx_list

    # --- string ---
    raw = str(hint).strip()

    if not raw:
        print("[resolve_index] empty str → use default:", ES_INDEX_DEFAULT)
        return ES_INDEX_DEFAULT

    # "a,b,c"
    if "," in raw:
        idx_list = [i.strip() for i in raw.split(",") if i.strip()]

        if not idx_list:
            print("[resolve_index] parsed empty list → use default:", ES_INDEX_DEFAULT)
            return ES_INDEX_DEFAULT

        if len(idx_list) == 1:
            print("[resolve_index] parsed single index →", idx_list[0])
            return idx_list[0]

        print("[resolve_index] parsed multi index →", idx_list)
        return idx_list

    # 單一 index
    print("[resolve_index] single index →", raw)
    return raw

def resolve_index_1217(hint: Optional[IndexType]) -> IndexType:
    """
    支援：
    - None           → 用 ES_INDEX_DEFAULT
    - "a"            → 單一 index
    - "a,b,c"        → 多 index
    - ["a","b","c"]  → 多 index
    """
    if hint is None:
        print("[_resolve_es_index] no hint, use default:", ES_INDEX_DEFAULT)
        return ES_INDEX_DEFAULT

    if isinstance(hint, list):
        idx_list = [str(i).strip() for i in hint if i and str(i).strip()]
        return idx_list or ES_INDEX_DEFAULT

    raw = str(hint).strip()
    if not raw:
        return ES_INDEX_DEFAULT

    if "," in raw:
        idx_list = [i.strip() for i in raw.split(",") if i.strip()]
        return idx_list or ES_INDEX_DEFAULT

    return raw


def safe_search(
    body: Dict[str, Any],
    *,
    index: Optional[IndexType] = None,
    allow_highlight_retry: bool = True,
):
    """
    封裝 ES.search：
    - 支援傳入 list index
    - 遇到 highlight / max_analyzed_offset 問題時，自動重試（移除 highlight）
    """
    idx = index or ES_INDEX_DEFAULT

    if not idx:
        raise RuntimeError(
            "ES_INDEX_DEFAULT 未設定，請在 .env 設定 ES_INDEX，例如 ES_INDEX=news_test"
        )

    # ES client 支援 "a,b" 或 ["a","b"]，這邊統一成字串比較保險        
    if isinstance(idx, list):
        es_index = ",".join(idx)
    else:
        es_index = idx

    try:
        return ES.search(
            index=es_index,
            body=body,
            request_timeout=int(os.getenv("ES_TIMEOUT", "30")),
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
                request_timeout=int(os.getenv("ES_TIMEOUT", "30")),
                params={"error_trace": "true"},
            )
        raise
