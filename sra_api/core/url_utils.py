#api/core/url_utils.py
#import os
from .settings import PUBLIC_API_BASE
from fastapi import Request

#PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")

def abs_url(request: Request, path: str) -> str:
    """
    依 PUBLIC_API_BASE（若有）或 request.base_url 組出絕對網址。
    """
    base = (PUBLIC_API_BASE or str(request.base_url)).rstrip("/")
    return f"{base}{path}"