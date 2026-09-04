import json,sqlite3
import pytest
from batch_scheduler.input_loader import load_batch
from batch_scheduler.store import BatchSchedulerStore,BatchConflictError

def fixture(tmp_path,prompt='p'):
 p=tmp_path/'x.json';p.write_text(json.dumps([{'task_id':'t','prompt':prompt}]));return load_batch(p)
def test_version_idempotency_and_restart(tmp_path):
 s=BatchSchedulerStore(tmp_path/'db'); s.initialize(); assert sqlite3.connect(tmp_path/'db').execute('pragma user_version').fetchone()[0]==1
 first=s.import_batch(fixture(tmp_path),'b',tmp_path/'out'); second=s.import_batch(fixture(tmp_path),'b',tmp_path/'out'); assert first==second
 t=s.list_tasks('b')[0]; assert t['session_id'] and t['idempotency_key'].startswith('batch-v1-')
 assert BatchSchedulerStore(tmp_path/'db').list_tasks('b')[0]['idempotency_key']==t['idempotency_key']
def test_import_conflict(tmp_path):
 s=BatchSchedulerStore(tmp_path/'db');s.import_batch(fixture(tmp_path),'b',tmp_path/'out')
 other=tmp_path/'y.json';other.write_text(json.dumps([{'task_id':'t','prompt':'different'}]))
 with pytest.raises(BatchConflictError):s.import_batch(load_batch(other),'b',tmp_path/'out')
