from datetime import timezone
import pytest
from pydantic import ValidationError
from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.profile import normalize_rows
from tests.requirement_test_support import sample_profile, sample_row

def test_trailing_header_datetime_and_hash_semantics():
    profile=ImportProfileDocument.model_validate(sample_profile()); first=normalize_rows([sample_row()],profile).rows[0]; second=normalize_rows([sample_row(UpdateApeno=99)],profile).rows[0]
    assert first.prompt_content=="prompt body" and first.title=="Test title" and first.source_updated_at.utcoffset()==timezone.utc.utcoffset(first.source_updated_at)
    assert first.source_row_hash!=second.source_row_hash and first.source_payload_hash!=second.source_payload_hash and first.execution_content_hash==second.execution_content_hash
def test_ambiguous_header_and_invalid_datetime_fail_closed():
    profile=ImportProfileDocument.model_validate(sample_profile()); row=sample_row(); row["CONTENT  "]="other"; result=normalize_rows([row],profile); assert result.has_errors and result.diagnostics[0].code=="mapping_ambiguous_column"
    assert normalize_rows([sample_row(UPDT="nonsense")],profile).diagnostics[0].code=="datetime_parse_error"
def test_profile_is_strict_and_immutable():
    value=sample_profile(); value["unknown"]=1
    with pytest.raises(ValidationError): ImportProfileDocument.model_validate(value)
    profile=ImportProfileDocument.model_validate(sample_profile())
    with pytest.raises(ValidationError): profile.source_timezone="UTC"
