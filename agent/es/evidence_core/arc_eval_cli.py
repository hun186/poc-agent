"""Local CLI for aggregate-only ARC paired evaluation; no provider or ES IO."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .arc_semantic_eval import evaluate_semantic_cases
from .arc_selection_eval import evaluate_selection_cases
from .arc_rank_replay import replay_rank_cases
from .arc_tighten_replay import replay_tightening_cases
from .arc_relax_replay import replay_relax_cases
from .arc_resource_eval import evaluate_resource_cases
from .arc_semantic_review import _unique_pairs

MAX_INPUT_BYTES = 2 * 1024 * 1024
_USAGE = "python -m agent.es.evidence_core.arc_eval_cli {semantic|selection|rank-replay|tighten-replay|relax-replay|resources} PRIVATE_LABELS.json"


def _emit(result, *, stream):
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False,
                     separators=(",", ":")), file=stream)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--help"] or args == ["-h"]:
        print(_USAGE)
        return 0
    if len(args) != 2 or args[0] not in ("semantic", "selection", "rank-replay", "tighten-replay", "relax-replay", "resources"):
        _emit({"status": "INVALID_ARGUMENTS", "usage": _USAGE}, stream=sys.stderr)
        return 2
    evaluator = {"semantic": evaluate_semantic_cases, "selection": evaluate_selection_cases,
                 "rank-replay": replay_rank_cases, "tighten-replay": replay_tightening_cases,
                 "relax-replay": replay_relax_cases, "resources": evaluate_resource_cases}[args[0]]
    try:
        # Operator-owned local file; never read stdin, URL, directory or pipe.
        path = Path(args[1])
        if not path.is_file():
            raise ValueError("not_regular_file")
        with path.open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise ValueError("input_size")
        cases = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs)
        result = evaluator(cases)
        if result is None:
            raise ValueError("invalid_fixture")
    except (OSError, ValueError, TypeError, RecursionError):
        # Do not reveal path, fixture contents, source ordinals or exception text.
        _emit({"status": "INVALID_OR_UNREADABLE_FIXTURE"}, stream=sys.stderr)
        return 2
    _emit({"status": "EVALUATED_OFFLINE", "result": result}, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
