from pathlib import Path

def test_pipeline_defaults_disabled_without_sql_configuration():
    source=Path("sra_api/main.py").read_text(); assert 'REQUIREMENT_PIPELINE_ENABLED", "false"' in source and "requirement_store.initialize()" in source
