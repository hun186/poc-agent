# api/core/settings.py
import os
from elasticsearch import Elasticsearch
from agent.direct_llm_json import OpenAIStyleOllama
from config.index_loader import INDEX_CONFIG   # ★ 新增：跟 agent 共用 index 設定
#from agent.es.es_client import ALL_INDEXES, ES_INDEX_DEFAULT
from agent.es.es_client import init_index_cache, ALL_INDEXES, ES_INDEX_DEFAULT

# ===== LLM / 模型設定 =====
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")

json_llm = OpenAIStyleOllama(
    base_url=os.getenv("MODEL_BASE_URL", "http://localhost:11434"),
    model=os.getenv("MODEL_ID", "gpt-oss:120b-32k"),
    temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
)

'''
# ===== Elasticsearch 設定 =====
ES_URL = os.getenv("ES_URL")
ES_USERNAME = os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ES_PASSWORD")
#ES_INDEX_RAW = os.getenv("ES_INDEX", "news_test,mil_reports-01")
CA_CERT = "agent/certs/http_ca.crt"

#ES_INDEXES = [idx.strip() for idx in ES_INDEX_RAW.split(",") if idx.strip()]

# ---- 1) 從 .env 讀 ES_INDEX（維持相容），如果沒設就用設定檔 default_index ----
default_idx_from_cfg = INDEX_CONFIG.get("default_index", "news_test")
ES_INDEX_RAW = os.getenv("ES_INDEX", default_idx_from_cfg)
ES_INDEXES_ENV = [idx.strip() for idx in ES_INDEX_RAW.split(",") if idx.strip()]

# ---- 2) 從 INDEX_CONFIG.topic_index_map 收集所有 index ----
topic_map = INDEX_CONFIG.get("topic_index_map", {}) or {}
cfg_indexes: list[str] = []
for cfg in topic_map.values():
    for idx in cfg.get("indexes") or []:
        if idx and idx not in cfg_indexes:
            cfg_indexes.append(idx)

# ---- 3) 合併去重：環境變數優先，其次設定檔 ----
ALL_INDEXES: list[str] = []
for idx in ES_INDEXES_ENV + cfg_indexes:
    if idx and idx not in ALL_INDEXES:
        ALL_INDEXES.append(idx)

# 為了向後相容：原本有在用 ES_INDEXES 的地方，直接等於 ALL_INDEXES
ES_INDEXES = ALL_INDEXES




ES = Elasticsearch(
    ES_URL,
    ca_certs=CA_CERT,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    ssl_assert_hostname=False,
)

print("Connecting to ES...")
print(ES.info())
'''
#init_index_cache(live_check=True)  # ✅ 這裡需要列出存在的 index，就用 True
# 預設不要在 import 階段連 ES，避免任何環境變數/憑證還沒就緒就爆
init_index_cache(live_check=os.getenv("ES_LIVE_CHECK", "0") == "1")
print("[settings] ES client ready, default index =", ES_INDEX_DEFAULT)
print("ALL_INDEXES =", ALL_INDEXES)  # ★ 看一下最後實際會查哪些 index

