"""Vercel Python runtime entrypoint.

Vercel's FastAPI preset looks for an `app` object in root-level entrypoints
such as `app.py`.  Keep the real application in `api.main` so local uvicorn
and existing imports continue to use the same FastAPI instance.
"""

from api.main import app

__all__ = ["app"]
