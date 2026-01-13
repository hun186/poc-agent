# config/index_loader.py
import yaml
import os
from pathlib import Path

def _normalize_indexes(raw):
    """
    支援：
    - ["a", "b"]
    - ["a,b,c"]
    - "a,b,c"
    回傳乾淨 list[str]（去空白、去重、保序）
    """
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]

    out = []
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
    
# 尋找 config/indexes.yaml（建議放在 repo_root/config/indexes.yaml）
'''
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "indexes.yaml"
)

CONFIG_PATH = os.getenv("INDEX_CONFIG", DEFAULT_CONFIG_PATH)
'''
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "indexes.yaml"
CONFIG_PATH = Path(
    os.getenv("INDEXES_CONFIG") or os.getenv("INDEX_CONFIG") or str(DEFAULT_CONFIG_PATH)
).resolve()

def load_index_mapping():
    if not os.path.exists(CONFIG_PATH):
        print(f"[index_loader] config file not found: {CONFIG_PATH}")
        return {
            "topic_index_map": {},
            "default": [],
        }

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # ★ 與 agent.py 使用方式保持一致
    topic_index_map = data.get("topic_index_map", {})   # ← 你 YAML 裡要用這個 key
    '''
    default_indexes = data.get("default", {}).get("indexes", []) \
                      if isinstance(data.get("default"), dict) \
                      else data.get("default", [])
    '''
    #default_raw = data.get("default", [])
    #if isinstance(default_raw, dict):
    #    default_indexes = default_raw.get("indexes", [])
    #else:
    #    default_indexes = default_raw
    default_indexes = data.get("default_indexes", [])       
    default_indexes = _normalize_indexes(default_indexes)
    print("[index_loader] loaded:", data)

    return {
        "topic_index_map": topic_index_map,
        "default": default_indexes,
    }


# singleton
INDEX_CONFIG = load_index_mapping()
