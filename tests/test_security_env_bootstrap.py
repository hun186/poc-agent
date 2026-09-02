import ast
from pathlib import Path


def test_cli_loads_dotenv_store_path(monkeypatch, tmp_path):
    store = tmp_path / "shared.json"
    monkeypatch.delenv("SRA_SERVICE_KEYS_FILE", raising=False)
    from api.security import cli
    monkeypatch.setattr(cli, "bootstrap_env", lambda: monkeypatch.setenv("SRA_SERVICE_KEYS_FILE", str(store)))
    cli.main(["create-service-key", "--name", "env", "--scope", "model:read"])
    assert store.exists()


def test_main_bootstraps_before_security_singleton(monkeypatch, tmp_path):
    tree = ast.parse(Path("sra_api/main.py").read_text(encoding="utf-8"))
    bootstrap = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "bootstrap_env")
    routers = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.ImportFrom) and node.module == "api.routers")
    assert bootstrap < routers
