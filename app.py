"""Vercel Python runtime entrypoint.

Keep the actual FastAPI application import path at ``api.main`` so local uvicorn
usage and existing imports continue to share the same application instance. The
``api`` package is now a small compatibility shim that points at ``sra_api``;
this keeps Vercel from treating the historical top-level ``api/`` source tree as
a directory full of Hobby-plan Serverless Functions.
"""

from api.main import app

__all__ = ["app"]
