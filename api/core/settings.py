# api/core/settings.py
import os
from elasticsearch import Elasticsearch
from agent.direct_llm_json import OpenAIStyleOllama

# ===== LLM / 模型設定 =====
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")

json_llm = OpenAIStyleOllama(
    base_url=os.getenv("MODEL_BASE_URL", "http://localhost:11434"),
    model=os.getenv("MODEL_ID", "gpt-oss:120b-32k"),
    temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
)

# ===== Elasticsearch 設定 =====
ES_URL = os.getenv("ES_URL")
ES_USERNAME = os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ES_PASSWORD")
ES_INDEX_RAW = os.getenv("ES_INDEX", "news_test,mil_reports-01")
CA_CERT = "agent/certs/http_ca.crt"

ES_INDEXES = [idx.strip() for idx in ES_INDEX_RAW.split(",") if idx.strip()]

ES = Elasticsearch(
    ES_URL,
    ca_certs=CA_CERT,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    ssl_assert_hostname=False,
)

print("Connecting to ES...")
print(ES.info())