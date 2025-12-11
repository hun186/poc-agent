# api/core/proctitle.py
import os
import socket

try:
    from setproctitle import setproctitle as _setproctitle
except ImportError:
    _setproctitle = None


def init_proctitle(app_name: str = "SRA-API") -> None:
    """
    根據環境變數設定 process title：
    - 程序名稱：app_name（預設 SRA-API）
    - 從 PUBLIC_API_BASE 解析 port，找不到時預設 9002
    - 從 MODEL_ID 取模型前綴（如 gpt-oss）
    """
    if _setproctitle is None:
        # 沒有安裝 setproctitle 就略過
        return

    public_base = os.getenv("PUBLIC_API_BASE", "").strip()
    model_id = os.getenv("MODEL_ID", "").strip()
    short_model = model_id.split(":", 1)[0] if model_id else ""

    port = "9002"
    if public_base:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(public_base)
            if parsed.port:
                port = str(parsed.port)
        except Exception:
            # 解析失敗就維持預設值
            pass

    host = socket.gethostname()
    pid = os.getpid()

    parts = [app_name, f"port={port}"]
    if short_model:
        parts.append(short_model)   # 例如 gpt-oss
    parts.append(f"pid={pid}")
    parts.append(host)

    title = " | ".join(parts)
    _setproctitle(title)
