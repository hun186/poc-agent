# agent/tools_es/common.py
from __future__ import annotations

import os
import json
from contextlib import nullcontext
from functools import wraps
from typing import Any, Dict, Iterable, List, Optional, Sequence
from typing import Iterable

from agent.es.es_client import resolve_index as _resolve_es_index


_REQUIREMENT_E2E_TOOL_SCOPE_ATTR = "_requirement_e2e_acceptance_scope"


def bind_requirement_acceptance(tool: Any) -> Any:
    """Capture verified E2E scope on a per-Agent tool instance.

    smolagents may execute tool.forward() in a worker thread that does not
    inherit ContextVar state.  The tool instance crosses that thread boundary,
    so capture only the current job-scoped acceptance bit on that instance.
    Production tools are bound False and can never activate the E2E scope.
    """
    from agent.external_capabilities import requirement_acceptance_active

    setattr(tool, _REQUIREMENT_E2E_TOOL_SCOPE_ATTR, bool(requirement_acceptance_active()))
    return tool


def requirement_acceptance_tool_scope(tool: Any):
    """Re-open the verified E2E scope inside a tool-execution thread."""
    from agent.external_capabilities import requirement_acceptance_scope

    if getattr(tool, _REQUIREMENT_E2E_TOOL_SCOPE_ATTR, False):
        return requirement_acceptance_scope()
    return nullcontext()


def propagate_requirement_acceptance(func):
    """Decorator for Tool.forward methods that may run in worker threads."""
    @wraps(func)
    def wrapped(self, *args, **kwargs):
        with requirement_acceptance_tool_scope(self):
            return func(self, *args, **kwargs)
    return wrapped


def dbg(*args: Any) -> None:
    """用環境變數控制 debug：ES_TOOLS_DEBUG=1 才會印。"""
    if os.getenv("ES_TOOLS_DEBUG", "0") == "1":
        print(*args)


def normalize_size(size: Optional[int], *, env_key: str = "ES_MAX_SIZE", default: int = 10000) -> int:
    max_size = int(os.getenv(env_key, str(default)))
    try:
        req = int(size) if size is not None else max_size
    except Exception:
        req = max_size
    return max(1, min(req, max_size))


def resolve_index(index_hint: Optional[str]) -> str:
    resolved = _resolve_es_index(index_hint)

    # 1) list/tuple -> join 成 ES 可吃的 "a,b,c"
    if isinstance(resolved, (list, tuple)):
        parts = [str(x).strip() for x in resolved if str(x).strip()]
        return ",".join(parts)

    s = (str(resolved) or "").strip()
    if not s:
        return s

    # 2) 防呆：如果長得像 "['a','b']" 就嘗試還原
    if s.startswith("[") and s.endswith("]"):
        try:
            import ast
            v = ast.literal_eval(s)
            if isinstance(v, (list, tuple)):
                parts = [str(x).strip() for x in v if str(x).strip()]
                return ",".join(parts)
        except Exception:
            pass

    return s



def split_indexes(resolved: Any) -> List[str]:
    """把 resolve_index 的結果轉成 list[str]，支援 'a,b,c' / list / tuple。"""
    if not resolved:
        return []
    if isinstance(resolved, (list, tuple)):
        out: List[str] = []
        for it in resolved:
            s = (str(it) or "").strip()
            if s:
                out.append(s)
        return out
    s = str(resolved).strip()
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]


def dot_get(d: Any, path: str) -> Any:
    """支援 'a.b.c' 讀取 nested dict。"""
    cur = d
    for p in (path or "").split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
        if cur is None:
            return None
    return cur


def flatten_syn_terms(grouped_syns: Dict[str, Iterable[str]]) -> List[str]:
    """把 grouped_syns 扁平化，去重、去空白，供 ES 查詢加分用。"""
    out: List[str] = []
    seen: set[str] = set()
    for syns in (grouped_syns or {}).values():
        for s in syns or []:
            if not isinstance(s, str):
                continue
            t = s.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


def term_groups_to_jsonable(term_groups: Iterable[Iterable[str]]) -> List[List[str]]:
    """term_groups 常是 list[set]，轉成 list[list] 才好序列化。"""
    out: List[List[str]] = []
    for g in term_groups or []:
        try:
            out.append(sorted([str(x) for x in g if str(x).strip()]))
        except Exception:
            out.append([])
    return out


def build_query_meta(
    *,
    raw_query: str,
    es_query: str,
    core_terms: List[str],
    syn_terms: List[str],
    effective_terms: List[str],
    manual_terms_in_q: List[str],
    is_manual_entity_query: bool,
    term_groups: Iterable[Iterable[str]],
    date_from: Optional[str],
    date_to: Optional[str],
) -> Dict[str, Any]:
    qm = {
        "query": raw_query,
        "es_query": es_query,
        "core_terms": core_terms or [],
        "syn_terms": syn_terms or [],
        "effective_terms": effective_terms or [],
        "manual_terms_in_q": manual_terms_in_q or [],
        "is_manual_entity_query": bool(is_manual_entity_query),
        "term_groups": term_groups_to_jsonable(term_groups),
        "date_from": date_from,
        "date_to": date_to,
    }
    dbg("[es_tools] query_meta =", json.dumps(qm, ensure_ascii=False))
    return qm
