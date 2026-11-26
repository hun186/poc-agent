"""Central ARC mode resolution, with legacy compatibility and no rollout authority.

No environment mutation, no authorization from configuration alone. The
shadow preset defaults to local observations only. Extra ES/model work
requires explicit feature opt-in and all existing independent permissions.
"""
from __future__ import annotations

import os

LOCAL_SHADOW_FLAGS = frozenset({
    "SRAF_ARC_GROUP_FREQUENCY",
    "SRAF_ARC_RANK",
    "SRAF_ARC_TIGHTEN",
    "SRAF_ARC_RELAX",
    "SRAF_ARC_ORDINARY_RESOURCE_METRICS",
    "SRAF_ARC_DEEP_RESOURCE_METRICS",
})
OPTIONAL_SHADOW_FLAGS = frozenset({
    "SRAF_ARC_BILINGUAL",
    "SRAF_ARC_STRATEGY",
    "SRAF_ARC_LLM_PRIORITY",
    "SRAF_ARC_ES_FREQUENCY",
    "SRAF_ARC_RANK_NATIVE",
    "SRAF_ARC_DEEP_FREQUENCY",
    "SRAF_ARC_RANK_DEEP",
    "SRAF_ARC_REVIEW_SCOPE",
    "SRAF_ARC_REVIEW",
    "SRAF_ARC_REVIEW_DEEP",
    "SRAF_ARC_REVIEW_RESOURCE_METRICS",
})
SHADOW_FLAGS = LOCAL_SHADOW_FLAGS | OPTIONAL_SHADOW_FLAGS


def arc_shadow_enabled(name: str) -> bool:
    if name not in SHADOW_FLAGS:
        return False
    mode = os.getenv("SRAF_ARC_MODE")
    # Unset retains the historical independent switches. Explicit off,
    # unsupported on, blank and malformed values deny all ARC observations.
    if mode is None:
        return os.getenv(name) == "shadow"
    if mode != "shadow":
        return False
    value = os.getenv(name)
    if value is None:
        return name in LOCAL_SHADOW_FLAGS
    return value == "shadow"
