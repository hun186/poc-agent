# agent/es/__init__.py
from .es_client import ES, ALL_INDEXES, ES_INDEX_DEFAULT, safe_search, resolve_index

__all__ = ["ES", "ALL_INDEXES", "ES_INDEX_DEFAULT", "safe_search", "resolve_index"]