from __future__ import annotations
import time, requests
from .config import BatchSchedulerConfig
DOCX='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
class BatchClientError(RuntimeError): pass
class BatchCredentialError(BatchClientError): pass
class BatchRemoteConflict(BatchClientError): pass
class BatchRemoteUnavailable(BatchClientError): pass
class BatchRemoteError(BatchClientError): pass
class InvalidDocxResponse(BatchClientError): pass
class SRAReportJobClient:
 def __init__(self,config,session=None,sleep=time.sleep): self.config=config; self.session=session or requests.Session(); self.sleep=sleep
 def _request(self,method,path,**kwargs):
  headers={'Authorization':f'Bearer {self.config.service_key}',**kwargs.pop('headers',{})}
  for attempt in range(self.config.max_retries+1):
   try: r=self.session.request(method,self.config.api_base+path,headers=headers,timeout=(self.config.connect_timeout,self.config.read_timeout),**kwargs)
   except (requests.Timeout,requests.ConnectionError) as exc:
    if attempt==self.config.max_retries: raise BatchRemoteUnavailable('report job API transport unavailable') from exc
    self.sleep(min(2**attempt,5)); continue
   if r.status_code in (401,403): raise BatchCredentialError(f'report job API credential rejected ({r.status_code})')
   if r.status_code in (429,502,503,504):
    if attempt==self.config.max_retries: raise BatchRemoteUnavailable(f'report job API unavailable ({r.status_code})')
    self.sleep(min(2**attempt,5)); continue
   if r.status_code==409: raise BatchRemoteConflict('report job API conflict (409)')
   if not 200<=r.status_code<300: raise BatchRemoteError(f'report job API request failed ({r.status_code})')
   return r
 def submit(self,*,batch_id,task):
  payload={'prompt':task['prompt'],'filename':task['filename'],'session_id':task['session_id'],'model':task['model'],'options':{},'metadata':{**__import__('json').loads(task['metadata_json']),'batch_id':batch_id,'task_id':task['task_id']}}
  data=self._request('POST','/v1/report/jobs',headers={'Idempotency-Key':task['idempotency_key']},json=payload).json()
  if not isinstance(data.get('job_id'),str): raise BatchRemoteError('invalid report job response')
  return data
 def status(self,job_id): return self._request('GET',f'/v1/report/jobs/{job_id}').json()
 def download(self,job_id):
  r=self._request('GET',f'/v1/report/jobs/{job_id}/word')
  if r.headers.get('Content-Type','').split(';')[0].strip().lower()!=DOCX: raise InvalidDocxResponse('download response is not DOCX')
  return r.content
