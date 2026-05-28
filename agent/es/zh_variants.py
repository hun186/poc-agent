import re
from typing import Any, List

try:
    from opencc import OpenCC
except Exception:
    OpenCC = None  # type: ignore[assignment]


def _contains_zh(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _build_opencc_converters() -> List[Any]:
    """
    建立多組 OpenCC 轉換器，涵蓋：
    - 地區詞彙轉換
    - 慣用詞轉換
    - 一詞多義與部分語境詞庫

    兩個方向都做：繁->簡 與 簡->繁。
    """
    if OpenCC is None:
        return []

    configs = [
        # 繁 -> 簡（含地區與慣用詞）
        "t2s",
        "tw2s",
        "tw2sp",
        "hk2s",
        # 簡 -> 繁（含地區與慣用詞）
        "s2t",
        "s2tw",
        "s2twp",
        "s2hk",
    ]

    converters: List[Any] = []
    for cfg in configs:
        try:
            converters.append(OpenCC(cfg))
        except Exception:
            continue
    return converters


_OPENCC_CONVERTERS = _build_opencc_converters()


def expand_zh_script_variants(term: str) -> List[str]:
    s = (term or "").strip()
    if not s:
        return []

    variants: List[str] = [s]

    if _contains_zh(s) and _OPENCC_CONVERTERS:
        for converter in _OPENCC_CONVERTERS:
            try:
                out = (converter.convert(s) or "").strip()
            except Exception:
                continue
            if out and out not in variants:
                variants.append(out)

    return variants
