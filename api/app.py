"""Vercel Python runtime entrypoint inside the required api directory.

Vercel applies the `functions` configuration to Python functions discovered
under `/api`. Keep the real FastAPI application in `api.main` so local uvicorn
and existing imports continue to use the same application instance.
"""

from api.main import app

__all__ = ["app"]
