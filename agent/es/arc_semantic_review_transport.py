"""A8 private bounded HTTPS model transport; not a live retrieval call site.

The caller must prove final canonical Evidence and authorized index scope
before building the private batch. Operator settings attest permitted data
egress; they are not a substitute for owner or document authorization.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from urllib3.exceptions import ReadTimeoutError

from .arc_request_budget import ArcUnits, current_arc_budget
from .ordinary_scope_receipt import current_ordinary_scope_capture
from .evidence_core.arc_semantic_review import (
    MAX_BATCH, MAX_INPUT_BYTES, SemanticReviewBatch, SYSTEM_PROMPT,
    summarize_semantic_review, _unique_pairs,
)

_LOG = logging.getLogger("sraf.arc.semantic_review")
_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
MAX_RESPONSE_BYTES = 65536
REQUEST_TIMEOUT_SECONDS = 15
MAX_PREDICT_TOKENS = 512


@dataclass(frozen=True, repr=False)
class _ApprovedEndpoint:
    url: str
    model: str
    index: str
    verify: bool | str


def _approved_endpoint(index):
    if (not arc_shadow_enabled("SRAF_ARC_REVIEW")
            or os.getenv("SRAF_ARC_REVIEW_EGRESS") != "approved"):
        return None
    endpoint = os.getenv("SRAF_ARC_REVIEW_ENDPOINT", "")
    model = os.getenv("SRAF_ARC_REVIEW_MODEL", "")
    approved = os.getenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "")
    if (type(index) is not str or not _INDEX.fullmatch(index) or ".." in index
            or index != approved or not endpoint or len(endpoint) > 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in endpoint)
            or not 0 < len(model) <= 240 or model != model.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in model)):
        return None
    try:
        parts = urlsplit(endpoint)
        if (parts.scheme != "https" or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.path != "/api/chat" or parts.query or parts.fragment
                or "?" in endpoint or "#" in endpoint or "\\" in endpoint
                or "%" in parts.netloc
                or (parts.port is not None and not 1 <= parts.port <= 65535)):
            return None
    except ValueError:
        return None
    ca = os.getenv("SRAF_ARC_REVIEW_CA_FILE")
    # Never accept false/0 as TLS bypass. A nonempty CA path is passed to
    # Requests as a path; missing or invalid certificates fail closed.
    return _ApprovedEndpoint(endpoint, model, index, ca if ca else True)


class _RejectedResponse(Exception):
    """A response rejected before Requests can buffer a redirect body."""


def _reject_unapproved_response(response, *args, **kwargs):
    # Session.send may prepare the next redirect even with allow_redirects=False.
    # Response hooks run BEFORE that code path. Closing the raw stream without
    # reading is essential for the same size/encoding bounds on rejected replies.
    if (response.status_code != 200
            or response.headers.get("Content-Encoding", "identity").lower() != "identity"):
        response.close()
        raise _RejectedResponse()
    return response


def _provider_count(value):
    # Provider-reported counts only; do not infer from bytes or reservations.
    return value if type(value) is int and 0 <= value <= 10**12 else None


def _request_review(approved, batch, *, metrics=None):
    payload = {
        "model": approved.model, "stream": False,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": batch.payload}],
        "options": {"num_predict": MAX_PREDICT_TOKENS},
    }
    # An isolated session avoids the global LLM singleton, environment
    # proxies/netrc, and redirects. No retry, no alternate provider.
    started = time.monotonic()
    body = bytearray()
    try:
        with requests.Session() as session:
            session.trust_env = False
            if metrics is not None:
                metrics["llm_calls"] = 1
            with session.post(
                approved.url, json=payload, timeout=(3, REQUEST_TIMEOUT_SECONDS),
                allow_redirects=False, verify=approved.verify, stream=True,
                headers={"Accept-Encoding": "identity"},
                hooks={"response": _reject_unapproved_response},
            ) as response:
                if (response.status_code != 200
                        or response.headers.get("Content-Encoding", "identity").lower() != "identity"):
                    return None
                for chunk in response.iter_content(chunk_size=4096):
                    if time.monotonic() - started > REQUEST_TIMEOUT_SECONDS:
                        if metrics is not None:
                            metrics["status"] = "timed_out"
                        return None
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        return None
                    body.extend(chunk)
    except _RejectedResponse:
        return None
    if time.monotonic() - started > REQUEST_TIMEOUT_SECONDS:
        if metrics is not None:
            metrics["status"] = "timed_out"
        return None
    try:
        envelope = json.loads(body, object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError):
        return None
    if type(envelope) is not dict or envelope.get("done") is not True:
        return None
    message = envelope.get("message")
    if type(message) is not dict or message.get("role") != "assistant" or message.get("tool_calls"):
        return None
    if metrics is not None:
        metrics["prompt_tokens"] = _provider_count(envelope.get("prompt_eval_count"))
        metrics["completion_tokens"] = _provider_count(envelope.get("eval_count"))
    return summarize_semantic_review(message.get("content"), batch)


def _measured_review(approved, batch):
    metrics = {"status": "failed", "elapsed_ms": None, "es_calls": 0,
               "llm_calls": 0, "prompt_tokens": None, "completion_tokens": None}
    started = time.monotonic_ns()
    try:
        summary = _request_review(approved, batch, metrics=metrics)
        if summary is not None:
            metrics["status"] = "completed"
    except requests.Timeout:
        summary = None
        metrics["status"] = "timed_out"
    except requests.ConnectionError as exc:
        # Requests iter_content wraps urllib3 ReadTimeoutError in a
        # ConnectionError. Do not classify unrelated connection failures
        # or infer timeout from provider-controlled exception text.
        summary = None
        if any(isinstance(arg, ReadTimeoutError) for arg in exc.args):
            metrics["status"] = "timed_out"
    except Exception:
        summary = None
    finally:
        metrics["elapsed_ms"] = (time.monotonic_ns() - started) // 1000000
    return summary, metrics


def observe_semantic_review(batch, *, index, authorize=None):
    """Count-only optional transport. Never returns per-passage decisions.

    Trusted runtime callers must pass an authorization callback for the exact
    resolved endpoint and their own source scope. The standalone transport
    uses explicit synthetic authorization in isolated tests; a budget reservation is not authorization.
    """
    if not arc_shadow_enabled("SRAF_ARC_REVIEW"):
        return
    from agent.external_capabilities import requirement_acceptance_active

    record = {"schema": "sraf_arc_semantic_review_shadow_v1", "status": "unavailable"}
    try:
        if requirement_acceptance_active() or current_ordinary_scope_capture() is not None:
            record["status"] = "unsupported_scope"
            return
        approved = _approved_endpoint(index)
        if approved is None:
            record["status"] = "egress_not_approved"
            return
        scope = current_arc_budget()
        if scope is None:
            record["status"] = "missing_shared_budget"
            return
        if (type(batch) is not SemanticReviewBatch
                or type(batch.count) is not int or not 1 <= batch.count <= MAX_BATCH
                or type(batch.payload) is not str
                or not 0 < len(batch.payload) <= MAX_INPUT_BYTES
                or len(batch.payload.encode("utf-8")) > MAX_INPUT_BYTES):
            record["status"] = "unsupported_batch"
            return
        if not callable(authorize) or authorize(approved) is not True:
            record["status"] = "source_or_endpoint_not_authorized"
            return
        budget, ordinal = scope
        if not budget.model_window_open():
            record["status"] = "model_deadline_or_scope_closed"
            return
        if not budget.reserve(ordinal, ArcUnits(llm_calls=1)):
            record["status"] = "shared_budget_exhausted"
            return
        measured = None
        if arc_shadow_enabled("SRAF_ARC_REVIEW_RESOURCE_METRICS"):
            summary, measured = _measured_review(approved, batch)
        else:
            summary = _request_review(approved, batch)
        if authorize(approved) is not True or not budget.model_window_open(admission=False):
            record["status"] = "authorization_or_deadline_changed"
        else:
            if measured is not None and measured["llm_calls"] == 1:
                _LOG.warning("SRAF_ARC_REVIEW_RESOURCE=%s", json.dumps(
                    {"schema": "sraf_arc_review_resource_v1",
                     "scope": "single_optional_model_adapter_attempt",
                     "measurement": measured}, sort_keys=True, separators=(",", ":")))
            if summary is None:
                record["status"] = "invalid_or_incomplete_response"
            else:
                record = summary
    except Exception:
        # No exception text, private payload, endpoint or provider response.
        record = {"schema": "sraf_arc_semantic_review_shadow_v1", "status": "unavailable"}
    finally:
        _LOG.warning("SRAF_ARC_SEMANTIC_REVIEW=%s",
                     json.dumps(record, sort_keys=True, separators=(",", ":")))
