#api/core/url_utils.py
import os
from fastapi import Request

PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")

def abs_url(request: Request, path: str) -> str:
    #print("PUBLIC_API_BASE",PUBLIC_API_BASE)
    base = (PUBLIC_API_BASE or str(request.base_url)).rstrip("/")
    #print("base",base)
    #print(f"href {base}{path}")
    return f"{base}{path}"