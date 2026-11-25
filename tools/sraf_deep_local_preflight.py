"""Local-only SRAF deep report configuration preflight.

No ES request, LLM inference, auth-store initialization, SQLite mutation,
report creation, service restart, or network probe. Only fixed statuses are
printed; a local pass is never live acceptance. Run with python -B.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_local(env, *, project_root: Path, require_auto: bool = False) -> dict:
    result = {
        "schema": "sraf_deep_local_preflight_v1",
        "scope": "LOCAL_CONFIGURATION_ONLY",
        "status": "INCOMPLETE",
        "configuration": "NOT_TESTED",
        "es_sdk_ca_setup": "NOT_TESTED",
        "local_model_configuration": "NOT_TESTED",
        "chat_auto": "NOT_TESTED",
        "browser_origin": "NOT_TESTED",
        "live_es_tls_mapping_and_read": "NOT_TESTED",
        "live_model_and_report": "NOT_TESTED",
        "live_account_grants": "NOT_TESTED",
        "live_openwebui_and_word": "NOT_TESTED",
    }
    from api.services.sraf_deep_startup_config import load_deep_startup_config
    try:
        config = load_deep_startup_config(env)
    except Exception:
        result.update(status="FAIL", configuration="FAIL", reason="deep_configuration_invalid")
        return result
    if config is None:
        result.update(status="FAIL" if require_auto else "INCOMPLETE",
                      configuration="DISABLED", chat_auto="DISABLED",
                      reason="deep_mode_disabled")
        return result

    auto = config.chat_auto_base_url
    result.update(configuration="PASS", local_model_configuration="PASS",
                  chat_auto="ENABLED" if auto else "DISABLED",
                  browser_origin=("HTTPS_CONFIGURED" if auto.startswith("https://") else
                                  "HTTP_CONFIGURED") if auto else "NOT_APPLICABLE")
    if require_auto and not auto:
        result.update(status="FAIL", reason="chat_auto_disabled")
        return result
    if require_auto and not auto.startswith("https://"):
        # Local policy allows HTTP for existing clients. The personal-token
        # OpenWebUI pilot requires verified HTTPS; don't pass it as ready.
        result.update(status="FAIL", reason="chat_auto_https_required_for_pilot")
        return result

    from api.services.sraf_deep_es_connection import build_deep_es_connection
    try:
        connection = build_deep_es_connection(env, project_root=project_root)
    except Exception:
        result.update(status="FAIL", es_sdk_ca_setup="FAIL", reason="deep_es_local_setup_invalid")
        return result
    try:
        connection.close()
    except Exception:
        result.update(status="FAIL", es_sdk_ca_setup="FAIL", reason="deep_es_local_cleanup_failed")
        return result
    result.update(status="PASS_PARTIAL", es_sdk_ca_setup="PASS",
                  reason="live_acceptance_not_run")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="read this checkout's dotenv/OS configuration and construct/close the local SDK")
    parser.add_argument("--require-auto", action="store_true",
                        help="also require automatic Chat mode and an HTTPS configured browser origin")
    args = parser.parse_args(argv)
    if not args.check:
        print(json.dumps({"schema": "sraf_deep_local_preflight_v1",
                          "status": "NOT_TESTED", "reason": "local_check_not_enabled"}))
        return 2
    if Path.cwd().resolve() != ROOT:
        print(json.dumps({"schema": "sraf_deep_local_preflight_v1",
                          "status": "FAIL", "reason": "run_from_repository_root"}))
        return 1
    # Bootstrap only this process. Suppress profile/path/warning outputs
    # from configuration loading, but do not misclassify broken imports.
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with redirect_stdout(sink), redirect_stderr(sink):
            from config.bootstrap import bootstrap_env
            try:
                bootstrap_env(project_root=ROOT)
            except Exception:
                result = {"schema": "sraf_deep_local_preflight_v1", "status": "FAIL",
                          "reason": "local_preflight_unavailable"}
            else:
                result = check_local(dict(os.environ), project_root=ROOT,
                                     require_auto=args.require_auto)
    print(json.dumps(result, sort_keys=True))
    # A partial result is deliberately not a release acceptance exit zero.
    return 1 if result["status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
