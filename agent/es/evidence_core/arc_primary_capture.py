"""Operator-only, read-only bounded ES sample capture for offline ARC A6.

No production agent, query expansion model, fallback, paging, or ES writes.
Input is an explicitly supplied local search specification, not an exact
recording of a production query. Output contains private ES response data.
"""
from __future__ import annotations

import base64
from datetime import date
import http.client
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
import time
from urllib.parse import urlsplit

from .arc_relax_annotation_cli import _load, _emit, MAX_FILE_BYTES
from .arc_semantic_review import _unique_pairs
from .arc_tighten_shadow import CandidatePressure
from .question_anchor import derive_explicit_question_anchor
from ..query_body import build_main_query_body

_INDEX = "news_test"
_MAX_HITS = 32
_MAX_SPEC_BYTES = 65536
_MAX_RESPONSE_BYTES = 1024 * 1024
_USAGE = "python -m agent.es.evidence_core.arc_primary_capture --run PRIVATE_SPEC.json PRIVATE_CASES.json"


def _build_spec(spec):
    if type(spec) is not dict or set(spec) != {
            "question", "query", "groups", "date_from", "date_to", "size"}:
        return None
    question, query, groups, start, end, size = (
        spec[k] for k in ("question", "query", "groups", "date_from", "date_to", "size"))
    if (type(question) is not str or not 0 < len(question) <= 6000
            or type(query) is not str or not 0 < len(query) <= 256 or not query.strip()
            or any(ord(c) < 32 for c in query)
            or type(size) is not int or not 1 <= size <= _MAX_HITS
            or type(start) is not str or type(end) is not str
            or date.fromisoformat(start).isoformat() != start
            or date.fromisoformat(end).isoformat() != end or start > end
            or (date.fromisoformat(end) - date.fromisoformat(start)).days > 3660
            or type(groups) is not list or not 3 <= len(groups) <= 8
            or any(type(g) is not list or not 1 <= len(g) <= 8
                   or any(type(t) is not str or not 0 < len(t) <= 160 or not t.strip()
                          or any(ord(c) < 32 for c in t) for t in g)
                   or len(set(g)) != len(g) for g in groups)
            or sum(map(len, groups)) > 32):
        return None
    if derive_explicit_question_anchor(question, [set(g) for g in groups]) is None:
        return None
    # Operator chooses group representatives, not a model-generated rewrite.
    core = [g[0] for g in groups]
    synonyms = list(dict.fromkeys(t for g in groups for t in g[1:]))
    all_terms = list(dict.fromkeys(t for g in groups for t in g))
    body = build_main_query_body(
        query, False, False, size, start, end, 6.0, 2.5,
        False, "importDT", "30d", with_date=True,
        effective_terms=all_terms, core_terms=core, syn_terms=synonyms,
        all_terms=all_terms, original_question=question)
    body["timeout"] = "5s"
    return body


def _connection_config():
    endpoint = urlsplit(os.environ["SRAF_ARC_CAPTURE_ES_URL"])
    host = endpoint.hostname
    ip = ipaddress.ip_address(host)
    if (endpoint.scheme != "https" or endpoint.username is not None
            or endpoint.password is not None or endpoint.path not in ("", "/")
            or endpoint.query or endpoint.fragment or endpoint.port is None
            or not 1 <= endpoint.port <= 65535
            or not (ip.is_private or ip.is_loopback)
            or ip.is_multicast or ip.is_unspecified or ip.is_link_local):
        raise ValueError("endpoint")
    username = os.environ["SRAF_ARC_CAPTURE_ES_USERNAME"]
    password = os.environ["SRAF_ARC_CAPTURE_ES_PASSWORD"]
    ca = Path(os.environ["SRAF_ARC_CAPTURE_ES_CA_FILE"])
    if not username or ":" in username or not password or not ca.is_file():
        raise ValueError("credentials")
    context = ssl.create_default_context(cafile=str(ca))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    auth = base64.b64encode((username + ":" + password).encode("utf-8")).decode("ascii")
    return host, endpoint.port, context, auth, username


def _read_json(config, method, path, payload=None, limit=65536):
    # Fixed callers, no proxy, redirect, retry or decompression. The socket
    # timeout is a per-operation timeout, not a hard wall-clock deadline.
    host, port, context, auth, _ = config
    conn = http.client.HTTPSConnection(host, port, timeout=8, context=context)
    try:
        conn.request(method, path, body=payload, headers={
            "Authorization": "Basic " + auth, "Accept": "application/json",
            "Content-Type": "application/json", "Accept-Encoding": "identity",
            "Connection": "close"})
        res = conn.getresponse()
        if res.status != 200 or res.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("http_rejected")
        length = res.getheader("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > limit):
            raise ValueError("response_size")
        raw = res.read(limit + 1)
        if not raw or len(raw) > limit:
            raise ValueError("response_size")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    finally:
        conn.close()


def capture_case(spec, *, request=_read_json, config=None):
    body = _build_spec(spec)
    if body is None:
        raise ValueError("spec")
    payload = json.dumps(body, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_SPEC_BYTES:
        raise ValueError("query_size")
    if config is None:
        config = _connection_config()
    principal = request(config, "GET", "/_security/_authenticate")
    if type(principal) is not dict or principal.get("username") != config[-1]:
        raise ValueError("principal")
    mapping = request(config, "GET", f"/{_INDEX}/_mapping", limit=_MAX_RESPONSE_BYTES)
    if type(mapping) is not dict or set(mapping) != {_INDEX}:
        raise ValueError("index_not_concrete")
    started = time.monotonic_ns()
    response = request(config, "POST",
                       f"/{_INDEX}/_search?allow_partial_search_results=false",
                       payload, limit=_MAX_RESPONSE_BYTES)
    elapsed = (time.monotonic_ns() - started) // 1000000
    pressure = CandidatePressure.from_primary(response)
    if pressure.relation not in ("eq", "gte") or not 1 <= pressure.returned <= spec["size"]:
        raise ValueError("invalid_search_result")
    rows = response["hits"]["hits"]
    ids = set()
    for h in rows:
        if (type(h) is not dict or h.get("_index") != _INDEX
                or type(h.get("_id")) is not str or not 0 < len(h["_id"]) <= 256
                or h["_id"] in ids or type(h.get("_source")) is not dict):
            raise ValueError("invalid_hit")
        ids.add(h["_id"])
    case = {k: spec[k] for k in ("question", "query", "groups", "date_from", "date_to")}
    case["response"] = response
    return case, {"returned": pressure.returned, "search_elapsed_ms": elapsed,
                  "es_search_attempts": 1, "es_preflight_attempts": 2}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        print(_USAGE)
        return 0
    if len(args) != 3 or args[0] != "--run":
        _emit({"status": "NOT_RUN", "usage": _USAGE}, sys.stderr)
        return 2
    target = Path(args[2])
    try:
        if os.path.lexists(target):
            raise ValueError("target_exists")
        spec = _load(Path(args[1]))
        if len(json.dumps(spec, ensure_ascii=False, allow_nan=False).encode("utf-8")) > _MAX_SPEC_BYTES:
            raise ValueError("spec_size")
        case, stats = capture_case(spec)
        encoded = (json.dumps([case], ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError("output_size")
    except Exception:
        _emit({"status": "CAPTURE_NOT_COMPLETED"}, sys.stderr)
        return 2
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(encoded)
            out.flush()
    except OSError:
        _emit({"status": "OUTPUT_NOT_COMPLETED_MAY_BE_PARTIAL"}, sys.stderr)
        return 2
    _emit({"status": "PRIVATE_PRIMARY_CAPTURED", **stats}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
