import pytest,requests
from pathlib import Path
from batch_scheduler.config import BatchSchedulerConfig
from batch_scheduler.sra_client import *
class R:
 def __init__(self,status=200,data=None,content=b'x',mime=DOCX):self.status_code=status;self._data=data or {};self.content=content;self.headers={'Content-Type':mime}
 def json(self):return self._data
class S:
 def __init__(self,responses):self.responses=list(responses);self.calls=[]
 def request(self,*a,**k):self.calls.append((a,k));return self.responses.pop(0)
def cfg():return BatchSchedulerConfig('http://x/','secret',max_retries=1)
def task():return {'prompt':'p','filename':None,'session_id':'s','model':'m','metadata_json':'{}','task_id':'t','idempotency_key':'idem'}
def test_submit_contract():
 s=S([R(202,{'job_id':'j'})]); assert SRAReportJobClient(cfg(),s).submit(batch_id='b',task=task())['job_id']=='j'; a,k=s.calls[0]; assert a==('POST','http://x/v1/report/jobs');assert k['headers']['Idempotency-Key']=='idem';assert k['json']['options']=={}
@pytest.mark.parametrize('code,error',[(401,BatchCredentialError),(403,BatchCredentialError),(409,BatchRemoteConflict),(400,BatchRemoteError),(404,BatchRemoteError)])
def test_nonretryable(code,error):
 with pytest.raises(error): SRAReportJobClient(cfg(),S([R(code)])).status('j')
def test_retryable():
 s=S([R(503),R(200,{'status':'running'})]);assert SRAReportJobClient(cfg(),s,sleep=lambda _:None).status('j')['status']=='running'
def test_download_mime():
 with pytest.raises(InvalidDocxResponse):SRAReportJobClient(cfg(),S([R(mime='text/plain')])).download('j')
