"""Vercel Python function entrypoint.

Keep this file as the only Vercel-routed Python function under top-level
``api/``. The compatibility package in ``api/__init__.py`` points imports at
``sra_api/``, so importing ``api.main`` below loads the real FastAPI app without
putting the full source tree under Vercel's function-discovery ``api/`` folder.
"""

from api.main import app

__all__ = ["app"]
