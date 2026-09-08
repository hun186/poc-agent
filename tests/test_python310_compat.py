from data_ingestion.requirements.models import (
    ImportProfileDocument,
    ProfileVersionStatus,
    SourceMode,
    SourceType,
)
from pydantic import TypeAdapter
from tests.requirement_test_support import sample_profile


def test_requirement_enum_values_remain_stable():
    assert {member.name: member.value for member in SourceType} == {
        "MANUAL_UPLOAD": "manual_upload",
        "FILE_PATH": "file_path",
        "SQL_QUERY": "sql_query",
    }
    assert {member.name: member.value for member in SourceMode} == {
        "AUTHORITATIVE_SNAPSHOT": "authoritative_snapshot",
        "UPSERT_DELTA": "upsert_delta",
    }
    assert {member.name: member.value for member in ProfileVersionStatus} == {
        "DRAFT": "draft",
        "APPROVED": "approved",
        "RETIRED": "retired",
    }


def test_requirement_enums_preserve_pydantic_parsing_and_serialization():
    payload = sample_profile()
    payload["source_mode"] = "upsert_delta"

    profile = ImportProfileDocument.model_validate(payload)

    assert profile.source_mode is SourceMode.UPSERT_DELTA
    assert profile.model_dump(mode="json")["source_mode"] == "upsert_delta"

    for enum_type, value in (
        (SourceType, "manual_upload"),
        (SourceMode, "authoritative_snapshot"),
        (ProfileVersionStatus, "approved"),
    ):
        adapter = TypeAdapter(enum_type)
        assert adapter.validate_python(value).value == value
        assert adapter.dump_python(adapter.validate_python(value), mode="json") == value
