# config/index_loader.py
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

from config.bootstrap import bootstrap_env
from shared.runtime_provenance import index_config_paths


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


def _split_paths(raw: str) -> List[Path]:
    """支援用逗號或 os.pathsep 分隔多個檔案路徑。"""
    if not raw:
        return []
    normalized = raw.replace(",", os.pathsep)
    return [Path(p).expanduser().resolve() for p in normalized.split(os.pathsep) if p.strip()]


def _merge_index_configs(base: Dict[str, Any], override: Dict[str, Any]):
    """後面的檔案覆蓋前面的設定（類似 .env.* 優先序）。"""
    merged = {
        "topic_index_map": dict(base.get("topic_index_map", {})),
        "default_indexes": list(base.get("default_indexes", [])),
    }
    merge_actions: List[str] = []

    if isinstance(override.get("topic_index_map"), dict):
        for topic, override_topic_cfg in override["topic_index_map"].items():
            base_topic_cfg = merged["topic_index_map"].get(topic, {})

            if isinstance(base_topic_cfg, dict) and isinstance(override_topic_cfg, dict):
                topic_cfg = dict(base_topic_cfg)
                topic_cfg.update(override_topic_cfg)

                # indexes 採擴增式覆蓋：保留前者 + 追加後者（去重、保序）
                base_indexes = _normalize_indexes(base_topic_cfg.get("indexes", []))
                override_indexes = _normalize_indexes(override_topic_cfg.get("indexes", []))
                if base_indexes or override_indexes:
                    topic_cfg["indexes"] = _normalize_indexes(base_indexes + override_indexes)
                    if override_indexes:
                        merge_actions.append(
                            f"topic={topic} indexes add {override_indexes} (base={base_indexes} -> merged={topic_cfg['indexes']})"
                        )

                for key, new_value in override_topic_cfg.items():
                    if key == "indexes":
                        continue
                    old_value = base_topic_cfg.get(key)
                    if old_value != new_value:
                        merge_actions.append(
                            f"topic={topic} field={key} overwrite {old_value!r} -> {new_value!r}"
                        )

                merged["topic_index_map"][topic] = topic_cfg
            else:
                merged["topic_index_map"][topic] = override_topic_cfg
                merge_actions.append(f"topic={topic} replaced by override config")

    if "default_indexes" in override:
        base_default_indexes = _normalize_indexes(merged.get("default_indexes", []))
        merged["default_indexes"] = _normalize_indexes(override.get("default_indexes", []))
        override_default_indexes = merged["default_indexes"]
        if base_default_indexes != override_default_indexes:
            merge_actions.append(
                f"default_indexes overwrite {base_default_indexes} -> {override_default_indexes}"
            )

    return merged, merge_actions


def _candidate_config_paths() -> List[Path]:
    # 讓 index_loader 即使被單獨 import，也能吃到 .env/.env.<env>/.env.local
    #（bootstrap_env 內部有 one-time guard，不會重複做重活）
    bootstrap_env()

    return index_config_paths(Path(__file__).resolve().parents[1], selector_base=Path.cwd())


def load_index_mapping():
    candidate_paths = _candidate_config_paths()
    print("[index_loader] merge policy: topic_index_map.<topic>.indexes = additive merge (base + override, dedup, keep-order); other fields last-file-wins")

    merged: Dict[str, Any] = {
        "topic_index_map": {},
        "default_indexes": [],
    }
    loaded_paths: List[str] = []

    for cfg_path in candidate_paths:
        if not cfg_path.exists():
            continue

        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        merged, merge_actions = _merge_index_configs(merged, data)
        if merge_actions:
            print(f"[index_loader] merge actions ({cfg_path}):")
            for action in merge_actions:
                print(f"[index_loader]   - {action}")
        loaded_paths.append(str(cfg_path))

    if not loaded_paths:
        print(f"[index_loader] config file not found, checked: {candidate_paths}")
        return {
            "topic_index_map": {},
            "default": [],
        }

    default_indexes = _normalize_indexes(merged.get("default_indexes", []))
    print(f"[index_loader] loaded from {loaded_paths}")

    merged_config = {
        "topic_index_map": merged.get("topic_index_map", {}),
        "default": default_indexes,
    }
    print("[index_loader] merged config:", merged_config)
    return merged_config


# singleton
INDEX_CONFIG = load_index_mapping()
