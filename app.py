"""Vercel Python runtime entrypoint.

Keep the actual FastAPI application in ``api.main`` so local uvicorn usage and
existing imports continue to share the same application instance. ``vercel.json``
uses an explicit @vercel/python build for this root file so Vercel does not
turn every Python module under the project ``api/`` package into a separate
Hobby-plan Serverless Function.
"""

from api.main import app

__all__ = ["app"]
