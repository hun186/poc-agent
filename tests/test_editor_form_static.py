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
    assert "(section.fields || []).forEach(field => setPath(item, field.path, defaultArrayFieldValue(field)));" in js
    assert "const arr = ensureArrayAtPath(path);" in js
    assert "if (rendered < arr.length) throw new Error" in js


def test_editor_form_asset_version_busts_array_schema_fix_cache():
    html = Path("sra_api/static/editor.html").read_text(encoding="utf-8")
    assert '<script src="/static/editor_form.js?v=20260625-array-preserve-single"></script>' in html
    assert '<script src="/static/editor_form.js?v=20260614-split"></script>' not in html


def test_editor_normalize_source_preserves_single_new_array_items():
    import subprocess
    import textwrap

    script = textwrap.dedent(
        r'''
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('sra_api/static/editor_core.js', 'utf8') + '\n' + fs.readFileSync('sra_api/static/editor_form.js', 'utf8') + `
        state.schema = {
          normalizers: {
            json_object_paths: ['multidim_event_json'],
            array_paths: ['multidim_event_json.Involved_Parties']
          },
          sections: [{
            type: 'array',
            path: 'multidim_event_json.Involved_Parties',
            fields: [{path: 'party_name', type: 'text'}]
          }]
        };
        const normalized = normalizeSource({multidim_event_json: {Involved_Parties: [{party_name: '新增'}]}});
        const parties = normalized.multidim_event_json.Involved_Parties;
        if (!Array.isArray(parties)) throw new Error('Involved_Parties was collapsed out of an array');
        if (parties.length !== 1) throw new Error('single new item was not preserved');
        if (parties[0].party_name !== '新增') throw new Error('single new item content was not preserved');
        `;
        vm.runInNewContext(code, {console, localStorage: {getItem: () => ''}});
        '''
    )
    subprocess.run(["node", "-e", script], check=True)
