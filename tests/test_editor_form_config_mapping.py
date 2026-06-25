from sra_api.services import editor_form_config


def _find_section(schema, path):
    return next(section for section in schema["sections"] if section.get("path") == path)


def _find_field(section, path):
    return next(field for field in section["fields"] if field.get("path") == path)


def test_editor_form_config_enriches_visible_fields_from_es_mapping(monkeypatch):
    mapping = {
        "multidim_event_json.Event_Timeline": {"type": "nested", "has_properties": True},
        "multidim_event_json.Event_Timeline.date_iso": {"type": "date"},
        "multidim_event_json.Event_Timeline.description": {"type": "text"},
        "multidim_event_json.evidence_snippets": {"type": "nested", "has_properties": True},
        "multidim_event_json.evidence_snippets.confidence": {"type": "integer"},
    }
    monkeypatch.setattr(
        editor_form_config,
        "get_index_field_metadata_map",
        lambda index: (mapping, True),
    )

    body = editor_form_config.public_editor_form_config(index="news-index")
    schema = body["schema"]

    assert body["mapping_ok"] is True
    assert body["mapping_field_count"] == len(mapping)

    timeline = _find_section(schema, "multidim_event_json.Event_Timeline")
    assert timeline["mapping"]["type"] == "nested"

    date_iso = _find_field(timeline, "date_iso")
    assert date_iso["mapping_path"] == "multidim_event_json.Event_Timeline.date_iso"
    assert date_iso["mapping"]["type"] == "date"
    assert date_iso["type"] == "date"

    description = _find_field(timeline, "description")
    assert description["mapping"]["type"] == "text"
    assert description["type"] == "textarea"

    evidence = _find_section(schema, "multidim_event_json.evidence_snippets")
    confidence = _find_field(evidence, "confidence")
    assert confidence["mapping_path"] == "multidim_event_json.evidence_snippets.confidence"
    assert confidence["mapping"]["type"] == "integer"
    assert confidence["type"] == "number"


def test_editor_form_config_keeps_layout_when_mapping_unavailable(monkeypatch):
    monkeypatch.setattr(
        editor_form_config,
        "get_index_field_metadata_map",
        lambda index: ({}, False),
    )

    body = editor_form_config.public_editor_form_config(index="offline-index")

    assert body["mapping_ok"] is False
    assert body["mapping_field_count"] == 0
    timeline = _find_section(body["schema"], "multidim_event_json.Event_Timeline")
    date_iso = _find_field(timeline, "date_iso")
    assert "mapping" not in date_iso
    assert date_iso["type"] == "text"
