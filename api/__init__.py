"""Compatibility package for the relocated application source.

The runtime modules live in ``sra_api/`` so Vercel does not treat the historical
``api/`` application package as a directory full of Serverless Functions. Keep
``import api.*`` working by pointing this package path at ``sra_api``.
"""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / "sra_api")]
