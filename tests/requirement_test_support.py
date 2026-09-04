from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from data_ingestion.requirements.models import ImportProfileDocument


def sample_profile(format="json"):
    return {"format": format, "source_timezone": "Asia/Taipei", "source_mode": "authoritative_snapshot", **({"worksheet": {"name": "工作表1", "header_row": 1, "first_data_row": 2, "trim_headers": True, "case_sensitive": False}} if format == "xlsx" else {}), "mapping": {
        "external_item_id": {"source": "ITEMNO", "required": True, "transforms": ["trim", "to_text"]},
        "title": {"source": "TITLE", "required": True, "transforms": ["trim", "normalize_whitespace"]},
        "prompt_content": {"source": "CONTENT", "aliases": ["CONTENT "], "required": True, "transforms": ["trim"]},
        "source_updated_at": {"source": "UPDT", "required": True, "type": "datetime", "transforms": ["to_datetime"]},
        "expires_at": {"source": "DeadlineDT", "type": "datetime", "transforms": ["empty_to_null", "to_datetime"]},
        "source_created_by": {"source": "CreateApeno", "type": "int", "transforms": ["empty_to_null", "to_int"]},
        "source_updated_by": {"source": "UpdateApeno", "type": "int", "transforms": ["empty_to_null", "to_int"]},
        "source_created_at": {"source": "CrtDT", "required": True, "type": "datetime", "transforms": ["to_datetime"]}}}


def sample_row(**changes):
    row = {"ITEMNO": "A001", "TITLE": " Test  title ", "CONTENT ": " prompt body ", "UPDT": "2026-09-04 09:00:00", "DeadlineDT": "2026-09-10 18:00:00", "CreateApeno": 11, "UpdateApeno": 12, "CrtDT": "2026-09-01 08:00:00"}; row.update(changes); return row


class MemoryStore:
    def __init__(self): self.profiles={}; self.versions={}; self.sources={}; self.current={}; self.runs={}; self.snapshots={}; self.sets={}
    def create_profile(self,name,description,actor,enabled=False,profile_id=None):
        pid=profile_id or uuid4().hex; self.profiles[pid]={"profile_id":pid,"name":name,"description":description,"enabled":enabled,"active_version_id":None}; return self.get_profile(pid)
    def get_profile(self,pid):
        if pid not in self.profiles: raise KeyError("profile_not_found")
        return {**self.profiles[pid],"versions":[{k:v for k,v in x.items() if k!="profile"} for x in self.versions.values() if x["profile_id"]==pid]}
    def list_profiles(self): return [self.get_profile(x) for x in self.profiles]
    def patch_profile(self,pid,actor,**changes): self.profiles[pid].update(changes); return self.get_profile(pid)
    def create_profile_version(self,pid,document,actor):
        profile=ImportProfileDocument.model_validate(document); number=sum(v["profile_id"]==pid for v in self.versions.values())+1; vid=uuid4().hex; self.versions[vid]={"profile_version_id":vid,"profile_id":pid,"version_number":number,"status":"draft","profile":profile,"profile_sha256":"a"*64}; return self.versions[vid]
    def get_profile_version(self,vid):
        if vid not in self.versions: raise KeyError("profile_version_not_found")
        return self.versions[vid]
    def approve_profile_version(self,pid,number,actor):
        version=next(v for v in self.versions.values() if v["profile_id"]==pid and v["version_number"]==number); version["status"]="approved"; self.profiles[pid]["active_version_id"]=version["profile_version_id"]; return version
    def get_active_profile_version(self,pid):
        profile=self.profiles[pid]
        if not profile["enabled"] or not profile["active_version_id"]: raise ValueError("profile_invalid")
        return self.versions[profile["active_version_id"]]
    def create_source(self,name,source_type,source_mode,source_config,import_profile_id,actor,enabled=False,source_id=None):
        sid=source_id or uuid4().hex; self.sources[sid]={"source_id":sid,"name":name,"source_type":source_type,"source_mode":source_mode,"source_config":source_config,"import_profile_id":import_profile_id,"enabled":enabled}; return self.sources[sid]
    def get_source(self,sid):
        if sid not in self.sources: raise KeyError("source_not_found")
        return self.sources[sid]
    def list_sources(self): return list(self.sources.values())
    def patch_source(self,sid,actor,**changes): self.sources[sid].update(changes); return self.sources[sid]
    def current_versions(self,sid): return self.current.get(sid,{})
    def commit_candidate(self,source,version,acquired,candidate,actor):
        if candidate.has_errors: return self.record_failed_import(source,version,acquired,candidate,actor)
        current=deepcopy(self.current.get(source["source_id"],{})); items=[]
        for row in candidate.rows:
            old=current.get(row.external_item_id)
            if old and row.source_updated_at<old["source_updated_at"]: raise ValueError("stale_source_version")
            if old and row.source_updated_at==old["source_updated_at"] and row.source_payload_hash!=old["source_payload_hash"]: raise ValueError("source_version_anomaly")
            value=row.model_dump(); value["requirement_version_id"]=(old or {}).get("requirement_version_id",uuid4().hex); current[row.external_item_id]=value; items.append(value)
        if source["source_mode"]=="upsert_delta": items += [v for k,v in current.items() if k not in {r.external_item_id for r in candidate.rows}]
        else: current={r.external_item_id:current[r.external_item_id] for r in candidate.rows}
        self.current[source["source_id"]]=current; run=uuid4().hex; snap=uuid4().hex; self.runs[run]={"import_run_id":run,"status":"committed"}; self.snapshots[snap]={"snapshot_id":snap,"source_snapshot_sha256":acquired.source_sha256,"import_profile_version_id":version["profile_version_id"],"items":items}; self.sets[source["source_id"]]={"requirement_set_id":source["source_id"],"active_snapshot_id":snap}; return {"import_run_id":run,"snapshot_id":snap,"status":"committed","accepted_count":len(items),"rejected_count":0}
    def record_failed_import(self,source,version,acquired,candidate,actor): run=uuid4().hex; self.runs[run]={"import_run_id":run,"status":"failed"}; return {"import_run_id":run,"snapshot_id":None,"status":"failed","accepted_count":len(candidate.rows),"rejected_count":len(candidate.diagnostics)}
    def get_import_run(self,x): return self.runs[x]
    def list_requirement_sets(self): return list(self.sets.values())
    def list_snapshots(self,x): return [v for v in self.snapshots.values()]
    def get_snapshot(self,x): return {k:v for k,v in self.snapshots[x].items() if k!="items"}
    def list_snapshot_items(self,x): return self.snapshots[x]["items"]
