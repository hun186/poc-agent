"""Compatibility package for the relocated application source.

The runtime modules live in ``sra_api/`` so Vercel does not treat the historical
``api/`` application package as a directory full of Serverless Functions. Keep
``import api.*`` working by searching this small shim directory first (for the
Vercel ``api.index`` function) and then the real ``sra_api`` source tree.
"""

from pathlib import Path

_API_SHIM_DIR = Path(__file__).resolve().parent
_SOURCE_DIR = _API_SHIM_DIR.parents[0] / "sra_api"

__path__ = [str(_API_SHIM_DIR), str(_SOURCE_DIR)]
