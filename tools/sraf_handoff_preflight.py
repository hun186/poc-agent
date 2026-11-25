"""Explicit local receiver preflight or one-time empty replay DB initialization.

No server start, provider call, account mutation, login, or secret output.
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--initialize-replay", action="store_true",
                      help="create a new replay DB only; never overwrite an existing file")
    args = parser.parse_args(argv)
    result = {"schema": "sraf_handoff_preflight_v1", "scope": "LOCAL_ONLY",
              "live_acceptance": "NOT_TESTED", "listener_started": False}
    if not args.check and not args.initialize_replay:
        result.update(status="NOT_TESTED", reason="explicit_operation_required")
        print(json.dumps(result, sort_keys=True))
        return 2
    if Path.cwd().resolve() != ROOT:
        result.update(status="FAIL", reason="run_from_repository_root")
        print(json.dumps(result, sort_keys=True))
        return 1
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with redirect_stdout(sink), redirect_stderr(sink):
            from config.bootstrap import bootstrap_env
            from api.security.sraf_handoff_config import load_handoff_receiver_config
            from api.security.sraf_handoff_assertion import HandoffDenied
            try:
                bootstrap_env(project_root=ROOT)
                config = load_handoff_receiver_config(dict(os.environ), project_root=ROOT,
                    require_replay=not args.initialize_replay)
                if config is None:
                    result.update(status="FAIL" if args.initialize_replay else "INCOMPLETE",
                                  reason="handoff_disabled")
                elif args.initialize_replay:
                    config.replay.initialize_new()
                    result.update(status="INITIALIZED", reason="new_replay_schema_created")
                else:
                    result.update(status="PASS_PARTIAL", reason="local_config_and_replay_schema_only",
                                  listener_mode=config.listener.mode)
            except HandoffDenied:
                result.update(status="FAIL", reason="handoff_config_or_replay_denied")
            except Exception:
                result.update(status="FAIL", reason="local_preflight_unavailable")
    print(json.dumps(result, sort_keys=True))
    if result["status"] == "INITIALIZED":
        return 0
    return 1 if result["status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
