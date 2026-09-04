from datetime import datetime
from io import BytesIO
import json
from openpyxl import Workbook
from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.service import RequirementImportService
from tests.requirement_test_support import MemoryStore

def workbook_bytes():
    workbook=Workbook(); sheet=workbook.active; sheet.title="工作表1"; sheet.append(["ITEMNO","TITLE","CONTENT ","UPDT","DeadlineDT","CreateApeno","UpdateApeno","CrtDT"])
    for number in range(1,11): sheet.append([f"R{number:03}",f"Title {number}",f"Prompt {number}",datetime(2026,9,4,9),datetime(2026,10,1,18),100+number,200+number,datetime(2026,9,1,8)])
    output=BytesIO(); workbook.save(output); return output.getvalue()

def test_taiwan_workbook_profile_imports_ten_canonical_members():
    profile=json.load(open("config/requirements/import_profile.taiwan-investment-security.v1.example.json",encoding="utf-8")); ImportProfileDocument.model_validate(profile)
    store=MemoryStore(); p=store.create_profile("p","","admin",enabled=True); version=store.create_profile_version(p["profile_id"],profile,"op"); store.approve_profile_version(p["profile_id"],1,"admin"); source=store.create_source("sample","manual_upload","authoritative_snapshot",{},p["profile_id"],"admin",enabled=True)
    result=RequirementImportService(store).commit(source["source_id"],actor="op",upload_bytes=workbook_bytes(),upload_filename="sample.xlsx"); snapshot=store.get_snapshot(result["snapshot_id"]); items=store.list_snapshot_items(result["snapshot_id"])
    assert result["accepted_count"]==10 and len(items)==10 and items[0]["prompt_content"]=="Prompt 1"
    assert items[0]["source_updated_at"].utcoffset().total_seconds()==0 and items[0]["expires_at"] is not None and items[0]["source_created_by"]==101 and items[0]["source_updated_by"]==201
    assert snapshot["import_profile_version_id"]==version["profile_version_id"] and len(snapshot["source_snapshot_sha256"])==64
