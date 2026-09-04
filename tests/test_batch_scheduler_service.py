import io,json,zipfile
from datetime import datetime,timezone,timedelta
from batch_scheduler.input_loader import load_batch
from batch_scheduler.store import BatchSchedulerStore
from batch_scheduler.service import BatchSchedulerService
from batch_scheduler.output import publish_docx,InvalidDocxError
import pytest

def docx():
 b=io.BytesIO();z=zipfile.ZipFile(b,'w');z.writestr('[Content_Types].xml','x');z.writestr('word/document.xml','x');z.close();return b.getvalue()
class Client:
 def __init__(self):self.submits=0
 def submit(self,**kw):self.submits+=1;return {'job_id':'same'}
 def status(self,j):return {'status':'completed'}
 def download(self,j):return docx()
def setup(tmp_path,scheduled=None):
 p=tmp_path/'i.json';p.write_text(json.dumps([{'task_id':'t','prompt':'p','filename':'../evil.docx','scheduled_at':scheduled}]))
 s=BatchSchedulerStore(tmp_path/'db');s.import_batch(load_batch(p),'b',tmp_path/'out');return s
def test_state_machine_download_and_confinement(tmp_path):
 s=setup(tmp_path); c=Client(); svc=BatchSchedulerService(s,c);svc.run_once('b'); assert s.list_tasks('b')[0]['state']=='downloaded';assert (tmp_path/'out') in __import__('pathlib').Path(s.list_tasks('b')[0]['output_path']).parents
 defused=False
def test_future_stays_pending(tmp_path):
 future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();s=setup(tmp_path,future);c=Client();BatchSchedulerService(s,c).run_once('b');assert c.submits==0

def test_resume_submitting_reuses_idempotency(tmp_path):
 s=setup(tmp_path);t=s.list_tasks('b')[0];s.mark_submitting('b','t');c=Client();BatchSchedulerService(s,c).run_once('b');assert c.submits==1;assert s.list_tasks('b')[0]['remote_job_id']=='same'
def test_invalid_docx_removed(tmp_path):
 with pytest.raises(InvalidDocxError):publish_docx(tmp_path,'t',None,b'bad')
 assert not list(tmp_path.glob('*.tmp'))
