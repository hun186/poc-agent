# agent/config/index_loader.py
import yaml
import os

# 尋找 config/indexes.yaml（建議放在 repo_root/config/indexes.yaml）
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "indexes.yaml"
)

CONFIG_PATH = os.getenv("INDEX_CONFIG", DEFAULT_CONFIG_PATH)


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
    default_indexes = data.get("default", {}).get("indexes", []) \
                      if isinstance(data.get("default"), dict) \
                      else data.get("default", [])

    print("[index_loader] loaded:", data)

    return {
        "topic_index_map": topic_index_map,
        "default": default_indexes,
    }


# singleton
INDEX_CONFIG = load_index_mapping()
