from pathlib import Path


def test_editor_array_render_initializes_missing_arrays_from_schema():
    js = Path("sra_api/static/editor_form.js").read_text(encoding="utf-8")
    assert "const items = ensureArrayAtPath(section.path);" in js
    assert "Documents can omit an" in js


def test_editor_form_config_covers_reference_nested_fields():
    config = Path("config/editor_form.default.json").read_text(encoding="utf-8")
    for field in ["date_raw", "date_precision", "party_role", "quote", "action", "stance", "relation", "confidence"]:
        assert f'"path": "{field}"' in config


def test_editor_array_add_uses_schema_item_fields_not_existing_doc_samples():
    js = Path("sra_api/static/editor_form.js").read_text(encoding="utf-8")
    assert "const section = schemaSections().find(s => s.type === 'array' && s.path === path);" in js
    assert "(section && section.fields || []).forEach(field => setPath(item, field.path, defaultArrayFieldValue(field)));" in js
    assert "const arr = ensureArrayAtPath(path);" in js


def test_editor_form_asset_version_busts_array_schema_fix_cache():
    html = Path("sra_api/static/editor.html").read_text(encoding="utf-8")
    assert '<script src="/static/editor_form.js?v=20260623-array-schema"></script>' in html
    assert '<script src="/static/editor_form.js?v=20260614-split"></script>' not in html
