from __future__ import annotations
import argparse

def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="python -m requirement_scheduler")
    parser.add_argument("command",choices=("handoff-worker",))
    return parser

def main(argv=None, *, coordinator_factory=None) -> int:
    args=build_parser().parse_args(argv)
    if args.command == "handoff-worker":
        if coordinator_factory is None:
            raise RuntimeError("handoff_configuration_required")
        import threading
        stop=threading.Event()
        try: coordinator_factory().run(stop)
        except KeyboardInterrupt: stop.set()
        return 0
    return 2
