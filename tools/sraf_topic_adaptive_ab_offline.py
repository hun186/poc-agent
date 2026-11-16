"""Read-only, zero-network baseline/shadow/on comparison on a private ES snapshot.

Input JSON is PRIVATE and never echoed. This tool does not download ES hits,
call an LLM, write report data, or claim precision without human labels.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import sys

from agent.es.evidence_core.builder import build_hits_and_evidence

MAX_FILE_BYTES = 8 * 1024 * 1024


def _private_read(path_text: str) -> dict:
    path = Path(path_text)
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= MAX_FILE_BYTES):
            raise ValueError("snapshot_not_private")
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
            data = json.load(stream)
    finally:
        os.close(fd)
    if not isinstance(data, dict):
        raise ValueError("snapshot_invalid")
    hits = data.get("es_hits")
    groups = data.get("term_groups")
    terms = data.get("effective_terms")
    if not isinstance(hits, list) or not 0 < len(hits) <= 1000:
        raise ValueError("snapshot_invalid")
    if any(not isinstance(x, dict) for x in hits):
        raise ValueError("snapshot_invalid")
    if (not isinstance(groups, list) or not 1 <= len(groups) <= 32
            or any(not isinstance(g, list) or not 0 < len(g) <= 32
                   or any(not isinstance(x, str) or len(x) > 64 for x in g)
                   for g in groups)):
        raise ValueError("snapshot_invalid")
    if not isinstance(terms, list) or len(terms) > 256 or any(
        not isinstance(x, str) or len(x) > 128 for x in terms
    ):
        raise ValueError("snapshot_invalid")
    if not isinstance(data.get("original_question"), str) or not (
        0 < len(data["original_question"]) <= 8192
    ):
        raise ValueError("snapshot_invalid")
    for key in ("date_from", "date_to"):
        if data.get(key) is not None and (
            not isinstance(data[key], str) or len(data[key]) > 24
        ):
            raise ValueError("snapshot_invalid")
    return data


def compare(data: dict) -> dict:
    original_setting = os.environ.get("SRAF_TOPIC_MATCH_ADAPTIVE")
    output: dict[str, list[dict]] = {}
    try:
        for mode in ("off", "shadow", "on"):
            os.environ["SRAF_TOPIC_MATCH_ADAPTIVE"] = mode
            _, snippets, _ = build_hits_and_evidence(
                copy.deepcopy(data["es_hits"]),
                date_from=data.get("date_from"),
                date_to=data.get("date_to"),
                allowed_years=None,
                term_groups=[set(g) for g in data["term_groups"]],
                effective_terms=data["effective_terms"],
                query_for_snippet=data.get("query_for_snippet") or "",
                original_question=data["original_question"],
                include_source_hit_ordinal=True,
            )
            output[mode] = snippets
    finally:
        if original_setting is None:
            os.environ.pop("SRAF_TOPIC_MATCH_ADAPTIVE", None)
        else:
            os.environ["SRAF_TOPIC_MATCH_ADAPTIVE"] = original_setting

    def n_sources(mode: str) -> int:
        return len({r["__sraf_source_hit_ordinal"] for r in output[mode]
                    if "__sraf_source_hit_ordinal" in r})

    return {
        "schema": "sraf_topic_adaptive_ab_v1",
        "scope": "private_same_snapshot_one_builder_not_live_es_or_recall",
        "baseline": len(output["off"]),
        "shadow": len(output["shadow"]),
        "shadow_equal_baseline": output["shadow"] == output["off"],
        "on": len(output["on"]),
        "adaptive_selected": sum(
            r.get("match_policy") == "adaptive_two_axis"
            for r in output["on"]
        ),
        "baseline_sources": n_sources("off"),
        "on_sources": n_sources("on"),
        "human_precision_assessment": "REQUIRED",
        "live_es_query": "NOT_TESTED",
        "report_docx": "NOT_TESTED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("RESULT=INCOMPLETE reason=snapshot_path_required")
        return 2
    try:
        metrics = compare(_private_read(argv[1]))
    except Exception:
        # Never echo details from malformed private snapshots or parser errors.
        print("RESULT=INCOMPLETE reason=invalid_or_unsafe_snapshot")
        return 2
    print("SRAF_TOPIC_ADAPTIVE_AB=" +
          json.dumps(metrics, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
