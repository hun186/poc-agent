import json
import pytest
from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.readers import read_bytes
from data_ingestion.requirements.source_adapters import acquire_source, validate_source_config
from data_ingestion.requirements.profile import normalize_rows
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

@pytest.mark.parametrize("header", ["CONTENT", "CONTENT "])
def test_csv_duplicate_and_normalized_duplicate_headers_are_ambiguous(header):
    profile=ImportProfileDocument.model_validate(sample_profile("csv"))
    rows,numbers=read_bytes(f"ITEMNO,TITLE,CONTENT,{header},UPDT,CrtDT\nA1,T,first,second,2026-09-04,2026-09-01\n".encode(),"rows.csv",profile)
    candidate=normalize_rows(rows,profile,numbers)
    assert candidate.has_errors
    assert candidate.diagnostics[0].code == "mapping_ambiguous_column"

def test_csv_nonempty_value_after_empty_header_is_preserved_not_discarded():
    profile=ImportProfileDocument.model_validate(sample_profile("csv"))
    rows,_=read_bytes(b"ITEMNO,TITLE,,CONTENT,UPDT,CrtDT\nA1,T,unexpected,P,2026-09-04,2026-09-01\n","rows.csv",profile)
    assert rows[0]["__column_3"] == "unexpected"

def test_sql_driver_failure_is_stable_and_connection_closes():
    class Connection:
        closed=False
        def cursor(self): raise RuntimeError("PWD=do-not-leak; reviewed SELECT secret")
        def close(self): self.closed=True
    connection=Connection()
    class Registry:
        def query(self, ref): return {"connection_ref":"safe","sql":"SELECT reviewed"}
        def open_named_connection(self, ref): return connection
    profile=ImportProfileDocument.model_validate({**sample_profile("json"),"format":"sql_rows"})
    with pytest.raises(RuntimeError, match="^sql_read_error$") as caught:
        acquire_source({"source_type":"sql_query","source_config":{"connection_ref":"safe","query_ref":"reviewed"}},profile,registry=Registry())
    assert "do-not-leak" not in str(caught.value) and connection.closed
