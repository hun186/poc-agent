"""Facade for user-operated Excel-to-SQL import workflows.

The implementation is split by responsibility so the public import path stays
stable while storage, preview scanning, and confirmed SQL imports remain small
and focused.
"""

from __future__ import annotations

from .user_import_preview import preview_record
from .user_import_runner import import_record
from .user_import_storage import (
    ACTIVE_DIR,
    ALLOWED_SUFFIXES,
    RECORDS_DIR,
    REGISTRY,
    ROOT,
    list_import_records,
    save_upload,
)

__all__ = [
    "ACTIVE_DIR",
    "ALLOWED_SUFFIXES",
    "RECORDS_DIR",
    "REGISTRY",
    "ROOT",
    "import_record",
    "list_import_records",
    "preview_record",
    "save_upload",
]
