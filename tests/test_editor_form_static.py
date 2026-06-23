from pathlib import Path


def test_editor_array_render_initializes_missing_arrays_from_schema():
    js = Path("sra_api/static/editor_form.js").read_text(encoding="utf-8")
    assert "const items = ensureArrayAtPath(section.path);" in js
    assert "Documents can omit an" in js


def test_editor_form_config_covers_reference_nested_fields():
    config = Path("config/editor_form.default.json").read_text(encoding="utf-8")
    for field in ["date_raw", "date_precision", "party_role", "quote", "action", "stance", "relation", "confidence"]:
        assert f'"path": "{field}"' in config
