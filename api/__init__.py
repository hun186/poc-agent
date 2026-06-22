"""Compatibility package for the relocated application source.

The runtime modules live in ``sra_api/`` so Vercel does not treat the historical
``api/`` application package as a directory full of Serverless Functions. Keep
``import api.*`` working by searching this small shim directory first (for the
Vercel ``api.index`` function) and then the real ``sra_api`` source tree.
"""

from pathlib import Path

_API_SHIM_DIR = Path(__file__).resolve().parent
_SOURCE_DIR = _API_SHIM_DIR.parents[0] / "sra_api"

# Prefer the relocated runtime source. Keep the shim directory second so
# Vercel can still import api.index without letting legacy conflict-resolution
# files shadow sra_api modules.
__path__ = [str(_SOURCE_DIR), str(_API_SHIM_DIR)]
