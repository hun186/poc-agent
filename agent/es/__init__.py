# agent/es/__init__.py

__all__ = ["get_es", "ALL_INDEXES", "ES_INDEX_DEFAULT", "safe_search", "resolve_index"]


def __getattr__(name):
    if name in __all__:
        from . import es_client

        return getattr(es_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
