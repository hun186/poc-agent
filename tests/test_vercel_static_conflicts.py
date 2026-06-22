from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "api" / "static"
VERCELIGNORE = ROOT / ".vercelignore"


def _vercelignore_entries() -> set[str]:
    return {
        line.strip()
        for line in VERCELIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_vercel_excludes_unused_swagger_ui_js_stem_conflict() -> None:
    index_html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    ignored = _vercelignore_entries()

    assert 'href="./swagger-ui.css"' in index_html
    assert "swagger-ui.js" not in index_html
    assert "api/static/swagger-ui.js" in ignored
    assert "api/static/swagger-ui.js.map" in ignored


def test_vercel_keeps_required_swagger_ui_assets() -> None:
    ignored = _vercelignore_entries()

    required_assets = {
        "api/static/swagger-ui.css",
        "api/static/swagger-ui-bundle.js",
        "api/static/swagger-ui-standalone-preset.js",
    }
    assert required_assets.isdisjoint(ignored)


def test_vercel_excludes_large_local_only_directories() -> None:
    ignored = _vercelignore_entries()

    large_local_only_dirs = {
        "data/",
        "technical_documents/",
        "logs/",
        ".api_state/",
        "sample_question/",
        "docs/",
        "tests/",
        ".codex/",
    }
    assert large_local_only_dirs.issubset(ignored)


def test_vercel_keeps_runtime_source_directories() -> None:
    ignored = _vercelignore_entries()

    runtime_source_dirs = {
        "api/",
        "agent/",
        "config/",
        "data_ingestion/",
        "portable_auth_pack/",
    }
    assert runtime_source_dirs.isdisjoint(ignored)
