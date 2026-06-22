# api/core/presenters/docx/config.py
from dataclasses import dataclass
import os
from typing import Tuple

@dataclass(frozen=True)
class DocxRenderConfig:
    # --- 表格合併策略 ---
    merge_safe_cols: Tuple[int, ...] = (0, 1)
    merge_col_block_if_ge: int = 9
    row_height_cv_threshold: float = 0.60
    sparsity_threshold: float = 0.72

    # --- 風格參考文本輸出 ---
    style_ref_max_docs: int = 5
    style_ref_max_chars: int = 2000

def load_docx_config_from_env() -> DocxRenderConfig:
    return DocxRenderConfig(
        style_ref_max_docs=int(os.getenv("DOCX_STYLE_REF_MAX_DOCS", "5")),
        style_ref_max_chars=int(os.getenv("DOCX_STYLE_REF_MAX_CHARS", "2000")),
        # 下面這些也可逐步開放 env；先固定在 config 內比較乾淨
    )
