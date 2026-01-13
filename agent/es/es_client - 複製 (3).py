# agent/es/es_client.py
import os
from typing import Any, Dict, Optional, Union, List
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, BadRequestError
from agent.config.index_loader import INDEX_CONFIG

load_dotenv()

IndexType = Union[str, List[str]]

# -----------------------------
# Index helpers
# -----------------------------
def _normalize_indexes(raw) -> List[str]:
    """
    接受：
    - ["a", "b"]
    - ["a,b,c"]  (你 YAML 現況)
    - "a,b,c"
    轉成乾淨 list[str]（去空白、去重、保序）
    """
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]

    out: List[str] = []
    seen = set()
    for it in raw:
        if it is None:
            continue
        s = str(it).strip()
        if not s:
            continue
        parts = [p.strip() for p in s.split(",") if p.strip()]
        for p in parts:
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _filter_existing_indexes(es: Elasticsearch, indexes: List[str]) -> List[str]:
    """只保留 ES 真的存在的 index，避免 search 直接噴 404 index_not_found_exception。"""
    ok: List[str] = []
    for idx in indexes:
        try:
            if es.indices.exists(index=idx):
                ok.append(idx)
            else:
                if os.getenv("ES_CLIENT_VERBOSE", "0") == "1":
                    print(f"[es_client] WARN missing index: {idx}")
        except Exception as e:
            if os.getenv("ES_CLIENT_VERBOSE", "0") == "1":
                print(f"[es_client] WARN exists check failed: {idx}: {e}")
            continue
    return ok


# -----------------------------
# 2) Elasticsearch connection
# -----------------------------
ES_URL = os.getenv("ES_URL")
ES_USERNAME = os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ES_PASSWORD")
ES_TIMEOUT = int(os.getenv("ES_TIMEOUT", "30"))

_HERE = os.path.dirname(os.path.abspath(__file__))               # .../agent/es
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..")) # .../poc-agent
CA_CERT = os.path.join(_PROJECT_ROOT, "agent", "certs", "http_ca.crt")

ES = Elasticsearch(
    ES_URL,
    ca_certs=CA_CERT if os.path.exists(CA_CERT) else None,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    ssl_assert_hostname=False,
    request_timeout=ES_TIMEOUT,
)

# -----------------------------
# 1) Index config integration (after ES is ready, so we can exists-check)
# -----------------------------

# ✅ 你 loader 回傳的是 "default": [...]，不是 default_index
_default_list_from_cfg = _normalize_indexes(INDEX_CONFIG.get("default") or [])
_default_one_from_cfg = _default_list_from_cfg[0] if _default_list_from_cfg else "news_test"

# env 的 ES_INDEX 優先（但也要 normalize）
ES_INDEX_RAW = os.getenv("ES_INDEX", _default_one_from_cfg)
ES_INDEXES_ENV = _normalize_indexes(ES_INDEX_RAW)

# topic map indexes
topic_map = INDEX_CONFIG.get("topic_index_map", {}) or {}
cfg_indexes: List[str] = []
for cfg in topic_map.values():
    if isinstance(cfg, dict):
        cfg_indexes.extend(_normalize_indexes(cfg.get("indexes") or []))
cfg_indexes = _normalize_indexes(cfg_indexes)

# ALL_INDEXES_RAW：設定宣告的全集（未做 exists 檢查）
ALL_INDEXES_RAW: List[str] = _normalize_indexes(ES_INDEXES_ENV + cfg_indexes)

# ALL_INDEXES：只保留存在的 index（給 API / tools 用）
ALL_INDEXES: List[str] = _filter_existing_indexes(ES, ALL_INDEXES_RAW)

# ✅ 預設 index：優先 env 第一個，其次 cfg default，最後才 fallback
_candidate_default = (ES_INDEXES_ENV[0] if ES_INDEXES_ENV else _default_one_from_cfg)
ES_INDEX_DEFAULT: str = _candidate_default

# 若 default 不存在，退回第一個 live index
if ALL_INDEXES and (ES_INDEX_DEFAULT not in ALL_INDEXES):
    ES_INDEX_DEFAULT = ALL_INDEXES[0]

# 若完全沒有 live index，就仍保留 candidate（但查詢時會 allow_no_indices）
# 這樣至少服務不會 import 就爆
if os.getenv("ES_CLIENT_VERBOSE", "0") == "1":
    print("[es_client] ES_INDEX_RAW =", ES_INDEX_RAW)
    print("[es_client] ES_INDEXES_ENV =", ES_INDEXES_ENV)
    print("[es_client] ALL_INDEXES_RAW =", ALL_INDEXES_RAW)
    print("[es_client] ALL_INDEXES(LIVE) =", ALL_INDEXES)
    print("[es_client] ES_INDEX_DEFAULT =", ES_INDEX_DEFAULT)
    try:
        print("[es_client] ES.info() =", ES.info())
    except Exception as e:
        print("[es_client] ES.info() failed:", e)


def get_es() -> Elasticsearch:
    return ES


def resolve_index(hint: Optional[Union[str, List[str]]]) -> IndexType:
    """
    hint 支援：
    - None → default
    - "a,b,c" → ["a","b","c"]（但若只剩 1 個就回傳字串）
    - ["a","b"] → 同上
    """
    if hint is None:
        return ES_INDEX_DEFAULT

    if isinstance(hint, list):
        idx_list = _normalize_indexes(hint)
    else:
        idx_list = _normalize_indexes(str(hint))

    if not idx_list:
        return ES_INDEX_DEFAULT
    return idx_list[0] if len(idx_list) == 1 else idx_list


def safe_search(
    body: Dict[str, Any],
    *,
    index: Optional[IndexType] = None,
    allow_highlight_retry: bool = True,
):
    """
    安全版 search：
    - 自動 ignore_unavailable / allow_no_indices，避免缺 index 就 404 → 500
    - highlight 造成 max_analyzed_offset 時自動降級重查
    """
    idx = index or ES_INDEX_DEFAULT
    es_index = ",".join(idx) if isinstance(idx, list) else (idx or ES_INDEX_DEFAULT)

    # ✅ 最後一道保險：永遠不要因缺 index 就炸
    params = {
        "error_trace": "true",
        "ignore_unavailable": "true",
        "allow_no_indices": "true",
    }

    try:
        return ES.search(
            index=es_index,
            body=body,
            request_timeout=ES_TIMEOUT,
            params=params,
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
                params=params,
            )
        raise
