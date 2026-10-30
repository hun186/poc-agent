"""Redacted, operator-opt-in strict ES TLS/Mapping observation for OFF-1 hub.

No ES requests occur unless the caller explicitly selects this module's
function. All network behavior is delegated to the existing bounded OFF-1B
implementation, with CA and numeric-IP SAN checks REQUIRED. This never
enables deliberately incorrect password challenges, write APIs or search.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping


_OBSERVED = {
    "https_probe": frozenset(("PASS", "FAIL", "SKIP")),
    "tls_validation": frozenset(("PASS", "FAIL", "WARN", "NOT_TESTED", "NOT_VERIFIED")),
    "mapping_probe": frozenset(("PASS", "FAIL", "SKIP", "WARN")),
    "auth": frozenset(("PASS", "FAIL", "NOT_VERIFIED", "NOT_TESTED")),
}


def strict_mapping_observation(cfg: Mapping[str, str], root: Path) -> dict[str, object]:
    """Map vetted OFF-1B probe to non-sensitive bounded evidence.

    A positive mapping result is **not** independent credential-principal
    authentication, source provenance, actual query execution, or release
    acceptance. Never return an overall PASS absent negative password control;
    that control is intentionally prohibited in this hub.
    """
    absent = {
        "check": "es_strict_tls_mapping", "status": "SKIP",
        "reason": "es_strict_observation_unavailable",
        "https_probe": "SKIP", "tls_validation": "NOT_TESTED",
        "mapping_probe": "SKIP", "auth": "NOT_TESTED",
        "credential_control": "NOT_RUN",
    }
    try:
        # Delayed import avoids even loading the authenticated probe for
        # ordinary diagnose/quick and --no-network invocations.
        from tools import sraf_airgap_off1b_es_https_mapping as es
        raw = es._observe(
            dict(cfg), no_network=False, root=root,
            verify_credentials=False, warn_only_ip_san=False,
        )
        if not isinstance(raw, dict):
            return absent
        # Any unexpected field, enum or relaxed peer policy is untrusted.
        if (raw.get("ip_san_policy") != "STRICT"
                or raw.get("credential_control") != "NOT_RUN"
                or raw.get("identity_warning") is not False):
            return absent
        if any(raw.get(k) not in allowed for k, allowed in _OBSERVED.items()):
            return absent
        row = {
            "check": "es_strict_tls_mapping",
            "status": "SKIP",
            "reason": "es_strict_incomplete",
            **{key: raw[key] for key in _OBSERVED},
            "credential_control": "NOT_RUN",
        }
        if raw["tls_validation"] == "FAIL":
            row.update(status="FAIL", reason="es_tls_identity_failed")
        elif raw["https_probe"] == "FAIL":
            row.update(status="FAIL", reason="es_https_identity_failed")
        elif raw["auth"] == "FAIL":
            row.update(status="FAIL", reason="es_auth_rejected")
        elif raw["mapping_probe"] == "FAIL":
            row.update(status="FAIL", reason="es_mapping_failed")
        elif (raw["tls_validation"] == "PASS"
              and raw["https_probe"] == "PASS"
              and raw["mapping_probe"] == "PASS"
              and raw["auth"] == "NOT_VERIFIED"):
            # Protected principal and mapping GET may be observed, but an
            # intermediary could override Basic auth. Do not fake success.
            row["reason"] = "es_tls_mapping_observed_auth_not_verified"
        return row
    except Exception:
        # Never leak native TLS/HTTP failures, endpoints or credentials.
        return absent
