import json
import pytest
from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.readers import read_bytes
from data_ingestion.requirements.source_adapters import acquire_source, validate_source_config
from tests.requirement_test_support import sample_profile, sample_row

def test_json_and_manual_filename_metadata_only(tmp_path):
    profile=ImportProfileDocument.model_validate(sample_profile()); content=json.dumps([sample_row()]).encode(); result=acquire_source({"source_type":"manual_upload","source_config":{}},profile,upload_bytes=content,upload_filename="../../rows.json")
    assert result.source_uri_display=="rows.json" and len(result.rows)==1
def test_file_path_confinement_and_exact_match(tmp_path):
    root=tmp_path/"root"; root.mkdir(); outside=tmp_path/"outside.json"; outside.write_text("[]")
    profile=ImportProfileDocument.model_validate(sample_profile())
    with pytest.raises(PermissionError): acquire_source({"source_type":"file_path","source_config":{"path":str(outside)}},profile,allowed_roots=str(root))
def test_format_and_config_fail_closed():
    profile=ImportProfileDocument.model_validate(sample_profile())
    with pytest.raises(ValueError): read_bytes(b"x","bad.xls",profile)
    with pytest.raises(ValueError): validate_source_config("sql_query",{"connection_ref":"c","query_ref":"q","sql":"select 1"})
