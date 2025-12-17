# agent/es/synonyms/__init__.py
from .manual import (
    MANUAL_SYNONYMS,
    load_manual_synonyms,
    expand_manual_terms,
    extract_manual_terms_from_query,
)

__all__ = [
    "MANUAL_SYNONYMS",
    "load_manual_synonyms",
    "expand_manual_terms",
    "extract_manual_terms_from_query",
]
