# agent/es/es_client.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union, List
#from dotenv import load_dotenv
from elasticsearch import Elasticsearch, BadRequestError
from elastic_transport import ObjectApiResponse
from config.bootstrap import bootstrap_env
from config.index_loader import INDEX_CONFIG
from api.services.vercel_mock_runtime import should_prefer_mock_runtime
from agent.es.mock_es_client import MOCK_INDEX, REQUIREMENT_E2E_INDEX, MockElasticsearch

#load_dotenv()

IndexType = Union[str, List[str]]
_ES: Elasticsearch | MockElasticsearch | None = None
_USING_MOCK_ES: bool = False

# 對外相容（避免 settings.py 直接 import 會爆）
ALL_INDEXES: List[str] = []      # 你可以選擇 raw 或 live（下面 init 控制）
ES_INDEX_DEFAULT: str = ""       # 最終 default（可能會被 live index 修正）
_INDEX_CACHE_READY: bool = False

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

def _project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))               # .../agent/es
    return os.path.abspath(os.path.join(here, "..", ".."))          # .../poc-agent


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
'''
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
'''
def _build_es() -> Elasticsearch:
    bootstrap_env()

    ES_URL = (os.getenv("ES_URL") or "").strip()
    if not ES_URL:
        raise RuntimeError(
            "ES_URL 未設定或未載入（請檢查 .env 是否有 ES_URL=...，"
            "以及 bootstrap_env() 是否真的有 load_dotenv）。"
        )

    ES_USERNAME = os.getenv("ES_USERNAME")
    ES_PASSWORD = os.getenv("ES_PASSWORD")
    ES_TIMEOUT = int(os.getenv("ES_TIMEOUT", "30"))

    project_root = _project_root()
    ca_cert = os.path.join(project_root, "agent", "certs", "http_ca.crt")

    return Elasticsearch(
        ES_URL,
        ca_certs=ca_cert if os.path.exists(ca_cert) else None,
        basic_auth=(ES_USERNAME, ES_PASSWORD),
        ssl_assert_hostname=False,
        request_timeout=ES_TIMEOUT,
    )

def get_es() -> Elasticsearch | MockElasticsearch:
    global _ES, _USING_MOCK_ES
    if _ES is None:
        from agent.external_capabilities import frozen_plan, resolve_environment_plan
        plan = frozen_plan(resolve_environment_plan)
        if plan is not None and plan.elasticsearch_backend == "semantic_mock":
            _ES = MockElasticsearch()
            _USING_MOCK_ES = True
            return _ES
        if should_prefer_mock_runtime():
            try:
                real = _build_es()
                if real.ping():
                    _ES = real
                    _USING_MOCK_ES = False
                else:
                    raise RuntimeError("Elasticsearch ping failed")
            except Exception as exc:
                if os.getenv("ES_CLIENT_VERBOSE", "0") == "1":
                    print(f"[es_client] using Vercel mock Elasticsearch: {exc}")
                _ES = MockElasticsearch()
                _USING_MOCK_ES = True
        else:
            _ES = _build_es()
            _USING_MOCK_ES = False
    return _ES


def using_mock_es() -> bool:
    return bool(_USING_MOCK_ES or isinstance(_ES, MockElasticsearch))

def init_index_cache(*, live_check: bool = False, force: bool = False) -> None:
    """
    初始化 ALL_INDEXES / ES_INDEX_DEFAULT：
    - live_check=False：不連 ES，不做 exists-check（最快、最不會在 import 時炸）
    - live_check=True ：會連 ES 並過濾不存在的 index（給 UI/tools 用）
    """
    global _INDEX_CACHE_READY, ALL_INDEXES, ES_INDEX_DEFAULT

    if _INDEX_CACHE_READY and not force:
        return

    bootstrap_env()

    if should_prefer_mock_runtime():
        try:
            es = get_es()
            if isinstance(es, MockElasticsearch):
                ALL_INDEXES = [MOCK_INDEX]
                ES_INDEX_DEFAULT = MOCK_INDEX
                _INDEX_CACHE_READY = True
                return
        except Exception:
            pass

    # 1) cfg default
    default_list = _normalize_indexes(INDEX_CONFIG.get("default") or [])
    default_one_from_cfg = default_list[0] if default_list else "news_test"

    # 2) env index（優先）
    es_index_raw = os.getenv("ES_INDEX", default_one_from_cfg)
    es_indexes_env = _normalize_indexes(es_index_raw)

    # 3) topic_index_map 收集
    topic_map = INDEX_CONFIG.get("topic_index_map", {}) or {}
    cfg_indexes: List[str] = []
    for cfg in topic_map.values():
        if isinstance(cfg, dict):
            cfg_indexes.extend(_normalize_indexes(cfg.get("indexes") or []))
    cfg_indexes = _normalize_indexes(cfg_indexes)

    # 4) 全集（raw）
    all_raw: List[str] = _normalize_indexes(es_indexes_env + cfg_indexes)

    # 5) default 候選（env 第一個 > cfg default）
    candidate_default = (es_indexes_env[0] if es_indexes_env else default_one_from_cfg)

    if live_check:
        # 需要 live index 時才連 ES
        es = get_es()
        all_live = _filter_existing_indexes(es, all_raw)

        ALL_INDEXES = all_live
        ES_INDEX_DEFAULT = candidate_default

        # default 不存在 → 退回第一個 live
        if ALL_INDEXES and ES_INDEX_DEFAULT not in ALL_INDEXES:
            ES_INDEX_DEFAULT = ALL_INDEXES[0]
    else:
        # 不查 exists：維持宣告全集
        ALL_INDEXES = all_raw
        ES_INDEX_DEFAULT = candidate_default

    _INDEX_CACHE_READY = True

    if os.getenv("ES_CLIENT_VERBOSE", "0") == "1":
        print("[es_client] ES_INDEX_RAW =", es_index_raw)
        print("[es_client] ALL_INDEXES =", ALL_INDEXES)
        print("[es_client] ES_INDEX_DEFAULT =", ES_INDEX_DEFAULT)

def _calc_default_index() -> str:
    from agent.external_capabilities import frozen_plan, resolve_environment_plan
    # Do not recursively probe while resolving the plan. A resolved semantic
    # backend always owns its explicit acceptance-only index.
    try:
        plan = frozen_plan()
    except Exception:
        plan = None
    if plan is not None and plan.elasticsearch_backend == "semantic_mock":
        return REQUIREMENT_E2E_INDEX
    init_index_cache(live_check=False)
    return ES_INDEX_DEFAULT or "news_test"
'''
def _calc_default_index() -> str:
    # ✅ 你 loader 現況：default 是 list
    default_list = _normalize_indexes(INDEX_CONFIG.get("default") or [])
    default_one = default_list[0] if default_list else "news_test"

    env_raw = os.getenv("ES_INDEX", default_one)
    env_indexes = _normalize_indexes(env_raw)

    return env_indexes[0] if env_indexes else default_one
'''
def resolve_index(hint: Optional[Union[str, List[str]]]) -> IndexType:
    default_idx = _calc_default_index()
    if hint is None:
        return default_idx

    idx_list = _normalize_indexes(hint if isinstance(hint, list) else str(hint))
    if not idx_list:
        return default_idx
    return idx_list[0] if len(idx_list) == 1 else idx_list

def _unwrap_es(res: Any) -> Dict[str, Any]:
    # ES 8.x 常見：ObjectApiResponse，資料在 .body
    if isinstance(res, ObjectApiResponse):
        return res.body or {}
    # 保底：如果剛好就是 dict
    if isinstance(res, dict):
        return res
    # 再保底：有些情況會有 .body
    if hasattr(res, "body") and isinstance(getattr(res, "body"), dict):
        return res.body
    return {}

def safe_search(
    body: Dict[str, Any],
    *,
    index: Optional[IndexType] = None,
    allow_highlight_retry: bool = True,
):
    es = get_es()
    ES_TIMEOUT = int(os.getenv("ES_TIMEOUT", "30"))

    # ✅ 先正確取得 idx（可能是 str 或 list）
    idx: IndexType = index if index is not None else _calc_default_index()

    # ✅ 修正：如果傳進來是空 list，就退回 default
    if isinstance(idx, list) and not idx:
        idx = _calc_default_index()

    # ✅ 修正：如果傳進來是空字串，也退回 default
    if isinstance(idx, str) and not idx.strip():
        idx = _calc_default_index()
        
    es_index = ",".join(idx) if isinstance(idx, list) else (idx or _calc_default_index())

    params = {
        "error_trace": "true",
        "ignore_unavailable": "true",
        "allow_no_indices": "true",
    }

    try:
        '''
        return es.search(
            index=es_index,
            body=body,
            request_timeout=ES_TIMEOUT,
            params=params,
        )
        '''
        res = es.search(
            index=es_index,
            body=body,
            request_timeout=ES_TIMEOUT,
            params=params,
        )
        #print("[safe_search] res type:", type(res))
        #if hasattr(res, "body"):
        #    print("[safe_search] has .body type:", type(res.body))
        #return res
        return _unwrap_es(res)
    
    except BadRequestError as e:
        info = str(getattr(e, "info", e))
        if allow_highlight_retry and ("max_analyzed_offset" in info or "highlight" in info):
            body2 = dict(body)
            body2.pop("highlight", None)
            '''
            return es.search(
                index=es_index,
                body=body2,
                request_timeout=ES_TIMEOUT,
                params=params,
            )
            '''
            res = es.search(
                index=es_index,
                body=body2,
                request_timeout=ES_TIMEOUT,
                params=params,
            )
            return _unwrap_es(res)
        raise

# --- legacy exports (相容舊 import) ---
# 讓 from agent.es.es_client import ES 不會爆
#ES = get_es()
# 模組載入時先用 raw 初始化，避免 import 後 ES_INDEX_DEFAULT/ALL_INDEXES 是空的
try:
    init_index_cache(live_check=False)
except Exception:
    # 不要因為初始化失敗就讓 import 爆掉
    pass
