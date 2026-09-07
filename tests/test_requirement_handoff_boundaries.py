from pathlib import Path

def test_bridge_has_no_forbidden_runtime_coupling():
    text="\n".join(p.read_text() for p in Path("requirement_scheduler").glob("*.py"))
    for name in ("langgraph", "ReportJobWorker", "ReportJobStore", "batch_scheduler.store"):
        assert name not in text
