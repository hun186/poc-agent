"""OFF-1F explicit, bounded one-shot Ollama inference (partial evidence only).

Operator-only helper. No CLI/network invocation on import. The caller must
verify both explicit CLI opt-ins, successful LLM inventory, and exact trusted
localhost HTTP scope BEFORE calling this helper.
"""
from __future__ import annotations

import json

from tools.sraf_airgap_off1_probes import (
    MAX_HTTP_BYTES, Observation, _http_post_local_generate,
)

PROMPT = "Reply with a single word: READY."
MAX_OUTPUT_TOKENS = 8
MAX_MODEL_LEN = 256


def _evidence(status: str, reason: str, *, executed: bool,
              http_status: int | None = None,
              generated: bool = False) -> Observation:
    data: dict[str, int | bool] = {"generation_observed": generated}
    if http_status is not None:
        data["http_status"] = http_status
    return Observation("LLM-02", "llm-inference",
                       "single_bounded_generation_only", status, reason,
                       executed, data)


def probe_local_ollama_inference(port: int, model: str) -> Observation:
    """Exactly one POST /api/generate to 127.0.0.1, never model acceptance.

    This request can load/compute a real model. A client timeout is not a
    server-side cancellation guarantee. No inference is attempted by default
    and this function is never called by normal application jobs.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        return _evidence("SKIP", "llm_inference_endpoint_invalid", executed=False)
    if (not isinstance(model, str) or not 1 <= len(model) <= MAX_MODEL_LEN
            or any(ord(c) < 33 or ord(c) > 126 for c in model)):
        return _evidence("SKIP", "llm_inference_model_invalid", executed=False)

    request = json.dumps({
        "model": model,
        "prompt": PROMPT,
        "stream": False,
        "options": {
            "num_predict": MAX_OUTPUT_TOKENS,
            "num_ctx": 512,
            "temperature": 0,
        },
    }, separators=(",", ":")).encode("ascii")
    if len(request) > 1024:
        return _evidence("SKIP", "llm_inference_request_invalid", executed=False)

    # Fixed endpoint and transport enforce numeric 127.0.0.1, no proxy/DNS,
    # no Authorization header, Content-Length, 64KiB response and 20s absolute
    # monotonic deadline. No retries even for overloaded/cold-start peers.
    status, body = _http_post_local_generate(port, request)
    if status is None:
        return _evidence("SKIP", "llm_inference_transport_unverified",
                         executed=True)
    if status in (401, 403, 429, 502, 503, 504):
        return _evidence("SKIP", "llm_inference_service_unverified",
                         executed=True, http_status=status)
    if status != 200:
        return _evidence("FAIL", "llm_inference_http_error",
                         executed=True, http_status=status)
    if body is None or len(body) > MAX_HTTP_BYTES:
        return _evidence("FAIL", "llm_inference_response_invalid",
                         executed=True, http_status=200)
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return _evidence("FAIL", "llm_inference_response_invalid",
                         executed=True, http_status=200)
    if not isinstance(obj, dict) or "error" in obj:
        return _evidence("FAIL", "llm_inference_response_invalid",
                         executed=True, http_status=200)
    if obj.get("model") != model:
        return _evidence("SKIP", "llm_inference_model_unverified",
                         executed=True, http_status=200)
    if (obj.get("done") is not True
            or not isinstance(obj.get("response"), str)
            or not 1 <= len(obj["response"].strip()) <= 1024
            or type(obj.get("eval_count")) is not int
            or not 1 <= obj["eval_count"] <= MAX_OUTPUT_TOKENS):
        return _evidence("SKIP", "llm_inference_generation_unverified",
                         executed=True, http_status=200)
    # Only observed bounded server generation, not result meaning/identity,
    # quality, RAG retrieval, SQL access or production inference availability.
    return _evidence("PASS", "llm_inference_generation_observed",
                     executed=True, http_status=200, generated=True)
