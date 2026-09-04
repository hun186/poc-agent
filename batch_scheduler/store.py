from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json, sqlite3, uuid
from .input_loader import LoadedBatch

class BatchConflictError(RuntimeError): pass
class BatchNotFoundError(KeyError): pass

def _now(): return datetime.now(timezone.utc).isoformat()
def _stable(prefix,batch,task): return prefix+sha256(f'{batch}\0{task}'.encode()).hexdigest()
class BatchSchedulerStore:
 def __init__(self,path): self.path=Path(path)
 def _connect(self):
  self.path.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(self.path,timeout=5); c.row_factory=sqlite3.Row; c.execute('PRAGMA busy_timeout=5000'); return c
 def initialize(self):
  with self._connect() as c:
   c.executescript('''CREATE TABLE IF NOT EXISTS batch_runs(batch_id TEXT PRIMARY KEY,source_path TEXT NOT NULL,source_sha256 TEXT NOT NULL,output_root TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','running','completed','completed_with_errors')),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batch_tasks(batch_id TEXT NOT NULL,task_id TEXT NOT NULL,source_order INTEGER NOT NULL,prompt TEXT NOT NULL,filename TEXT,session_id TEXT NOT NULL,model TEXT NOT NULL,scheduled_at TEXT,metadata_json TEXT NOT NULL,idempotency_key TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','submitting','submitted','running','downloading','downloaded','report_failed','interrupted','error')),remote_job_id TEXT,remote_status TEXT,output_path TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(batch_id,task_id),UNIQUE(idempotency_key),FOREIGN KEY(batch_id) REFERENCES batch_runs(batch_id)); PRAGMA user_version=1;''')
 def import_batch(self,loaded:LoadedBatch,batch_id:str,output_root):
  self.initialize(); now=_now()
  with self._connect() as c:
   old=c.execute('SELECT * FROM batch_runs WHERE batch_id=?',(batch_id,)).fetchone()
   if old:
    if old['source_sha256']!=loaded.source_sha256: raise BatchConflictError('batch_id already exists with different source')
    return dict(old)
   c.execute('INSERT INTO batch_runs VALUES(?,?,?,?,?,?,?)',(batch_id,str(loaded.source_path),loaded.source_sha256,str(Path(output_root).resolve()),'pending',now,now))
   for i,t in enumerate(loaded.tasks):
    session=t.session_id or 'batch-'+sha256(f'{batch_id}\0{t.task_id}'.encode()).hexdigest()[:32]
    key=_stable('batch-v1-',batch_id,t.task_id)
    c.execute('INSERT INTO batch_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(batch_id,t.task_id,i,t.prompt,t.filename,session,t.model,t.scheduled_at.isoformat() if t.scheduled_at else None,json.dumps(t.metadata,sort_keys=True,separators=(',',':')) ,key,'pending',None,None,None,None,now,now))
  return self.get_batch(batch_id)
 def get_batch(self,batch_id):
  with self._connect() as c: row=c.execute('SELECT * FROM batch_runs WHERE batch_id=?',(batch_id,)).fetchone()
  if not row: raise BatchNotFoundError(batch_id)
  return dict(row)
 def list_tasks(self,batch_id):
  with self._connect() as c: return [dict(x) for x in c.execute('SELECT * FROM batch_tasks WHERE batch_id=? ORDER BY source_order',(batch_id,))]
 def list_due_tasks(self,batch_id,now):
  return [x for x in self.list_tasks(batch_id) if x['state'] in ('pending','submitting') and (not x['scheduled_at'] or datetime.fromisoformat(x['scheduled_at']) <= now)]
 def update(self,batch_id,task_id,state,**fields):
  allowed={'remote_job_id','remote_status','output_path','error'}; bad=set(fields)-allowed
  if bad: raise ValueError('invalid update fields')
  values={'state':state,'updated_at':_now(),**fields}; sql=', '.join(f'{k}=?' for k in values)
  with self._connect() as c: c.execute(f'UPDATE batch_tasks SET {sql} WHERE batch_id=? AND task_id=?',(*values.values(),batch_id,task_id))
 def mark_submitting(self,b,t): self.update(b,t,'submitting',error=None)
 def record_submission(self,b,t,j): self.update(b,t,'submitted',remote_job_id=j,remote_status='pending')
 def record_remote_status(self,b,t,s): self.update(b,t,('report_failed' if s=='failed' else s),remote_status=s)
 def mark_downloading(self,b,t): self.update(b,t,'downloading')
 def mark_downloaded(self,b,t,p): self.update(b,t,'downloaded',output_path=str(p),remote_status='completed')
 def mark_error(self,b,t,e): self.update(b,t,'error',error=str(e))
