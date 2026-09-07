import ast
from pathlib import Path

ROOT=Path("requirement_scheduler")
FORBIDDEN_MODULES=("langgraph","smolagents","agent.agent","agent.report_agent","batch_scheduler")
FORBIDDEN_SYMBOLS={"ReportJobWorker","ReportJobStore","BatchSchedulerStore","BatchSchedulerService"}

def modules():
    for path in ROOT.glob("*.py"):
        yield path,ast.parse(path.read_text(),filename=str(path))

def test_bridge_import_graph_has_no_legacy_future_or_sibling_controller_coupling():
    for path,tree in modules():
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                assert all(not a.name.startswith(FORBIDDEN_MODULES) for a in node.names),path
            if isinstance(node,ast.ImportFrom) and node.module:
                assert not node.module.startswith(FORBIDDEN_MODULES),path
                assert not ({a.name for a in node.names}&FORBIDDEN_SYMBOLS),path

def test_bridge_does_not_define_future_task_attempt_or_event_authority():
    for path,tree in modules():
        names={n.name for n in ast.walk(tree) if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))}
        assert not (names & {"Task","Attempt","ExecutionEventStore","cancel_execution"}),path

def test_no_fastapi_thread_or_caller_artifact_root_contract():
    for path,tree in modules():
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        assert "fastapi" not in imports,path
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                args={a.arg for a in (*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs)}
                if node.name not in {"__init__","publish_or_reconcile"}:
                    assert "output_root" not in args,path
