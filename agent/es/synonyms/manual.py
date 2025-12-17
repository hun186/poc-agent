# agent/es/synonyms/manual.py
from typing import Dict, List, Any
import os, json

# ================== 人工同義詞：支援外部 config 覆蓋（多檔案） ==================

# 預設內建一份（防止沒給 config 也能用）
_DEFAULT_MANUAL_SYNONYMS: Dict[str, List[str]] = {
  #"東風": ["東風", "東風飛彈", "東風導彈", "DF", "DF-"],
  #"DF-11": ["DF-11", "DF11", "東風11", "東風-11", "東風11型", "東風11型導彈"],
  #"DF-15": ["DF-15", "DF15", "東風15", "東風-15", "東風15型", "東風15型導彈"],
  #"DF-21": ["DF-21", "DF21", "東風21", "東風-21", "東風21型", "東風21型導彈"],
  #"055": ["055", "055大驅", "055型驅逐艦", "驅逐艦055"]
    # 之後你可以自己加：
    # "094": [...],
    # "山東號": [...],
    # "遼寧號": [...],
}


def _merge_syn_dict(
    base: Dict[str, List[str]],
    data: Any,
    source_name: str = "<unknown>",
) -> None:
    """
    把 data (dict) 內容 merge 進 base：
    - 同一個 key，如果多個檔案都有，就把 list 做「去重後 append」，不會洗掉舊的。
    """
    if not isinstance(data, dict):
        print(f"[ES tools] 同義詞來源 {source_name} 不是 dict，略過")
        return

    for k, v in data.items():
        key = str(k)
        if isinstance(v, list):
            new_list = [str(x) for x in v]
        else:
            new_list = [str(v)]

        old_list = base.get(key, [])
        # 保留原有順序，把新來但沒出現過的詞 append 上去
        merged = old_list + [x for x in new_list if x not in old_list]
        base[key] = merged


def _merge_syn_dict_new_unused(base: Dict[str, List[str]],
                    override: Dict[str, List[str]]) -> Dict[str, List[str]]:
    # 原本的 _merge_syn_dict
    merged = dict(base)
    for k, v in (override or {}).items():
        if not v:
            continue
        merged.setdefault(k, [])
        for term in v:
            if term not in merged[k]:
                merged[k].append(term)
    return merged


def load_manual_synonyms() -> Dict[str, List[str]]:
    """
    載入人工同義詞（只有「目錄模式」）：

    1) 先用 _DEFAULT_MANUAL_SYNONYMS 打底
    2) 從 MANUAL_SYNONYMS_DIR（預設 config/synonyms）底下讀取所有 .json
    3) 依序 merge 成一份 dict

    若資料夾不存在或讀檔失敗，就只用預設表。
    """
    # 1) 先打底
    base: Dict[str, List[str]] = {
        k: list(v) for k, v in _DEFAULT_MANUAL_SYNONYMS.items()
    }

    # 2) 目錄設定（可用環境變數覆蓋）
    dir_path = os.getenv("MANUAL_SYNONYMS_DIR", "config/synonyms")

    if not os.path.isdir(dir_path):
        print(f"[ES tools] 同義詞資料夾不存在：{dir_path}，只使用內建預設表（{len(base)} 組 key）")
        return base

    loaded_files = 0
    for filename in os.listdir(dir_path):
        if not filename.lower().endswith(".json"):
            continue
        full_path = os.path.join(dir_path, filename)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _merge_syn_dict(base, data, source_name=full_path)
            loaded_files += 1
        except Exception as e:
            print(f"[ES tools] 讀取同義詞檔案失敗：{full_path}，錯誤：{e}")

    print(
        f"[ES tools] 已載入人工同義詞表，自資料夾 {dir_path} "
        f"共 {loaded_files} 個檔案，合計 {len(base)} 組 key（含預設 + merge）"
    )

    return base


# 實際使用的同義詞表
MANUAL_SYNONYMS: Dict[str, List[str]] = load_manual_synonyms()


def expand_manual_terms(tokens: List[str]) -> List[str]:
    """
    根據輸入 tokens 決定要展開哪幾組 MANUAL_SYNONYMS：
    - 若命中任何「特定型號 key」（key 名含數字，例如 DF-15）：
        → 只展開這些型號的同義詞，不把其他兄弟型號 / 家族詞一起帶進來。
    - 若沒有命中特定型號，而是只有「東風」這種泛稱：
        → 視為家族查詢，展開對應家族 key（例如 "東風" 那一條）。
    """
    def _is_specific_model_key(k: str) -> bool:
        return any(ch.isdigit() for ch in k)

    matched_model_keys: set[str] = set()
    matched_family_keys: set[str] = set()

    for raw in tokens:
        t = (raw or "").strip()
        if not t:
            continue

        for key, syns in MANUAL_SYNONYMS.items():
            if t == key or t in syns:
                if _is_specific_model_key(key):
                    matched_model_keys.add(key)
                else:
                    matched_family_keys.add(key)

    keys_to_use: set[str]
    if matched_model_keys:
        # 查到特定型號 → 只用這些型號
        keys_to_use = matched_model_keys
    else:
        # 否則才用家族 key（例如「東風」）
        keys_to_use = matched_family_keys

    expanded: set[str] = set()
    for k in keys_to_use:
        expanded.add(k)
        for v in MANUAL_SYNONYMS.get(k, []):
            expanded.add(v)

    return list(expanded)


def extract_manual_terms_from_query(q: str) -> List[str]:
    """
    直接在使用者 query 裡掃一遍 MANUAL_SYNONYMS：
    - 只要 query 字串中有出現 key 或 synonyms，就當成一個命中的人工同義詞。
    - 例如 query="給我東風15型導彈的情資"
      → 命中 "東風15" / "東風15型導彈" 等，就能回推到 DF-15 那條家族。
    """
    if not q:
        return []
    s = str(q)
    found: set[str] = set()
    for key, syns in MANUAL_SYNONYMS.items():
        # key 本身也要判
        if key and key in s:
            found.add(key)
        for t in syns:
            t = (t or "").strip()
            if t and t in s:
                found.add(t)
    return list(found)