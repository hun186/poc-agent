from datetime import datetime, timezone
from .sra_client import BatchCredentialError
from .output import publish_docx
class BatchSchedulerService:
 def __init__(self,store,client,clock=lambda:datetime.now(timezone.utc)): self.store=store; self.client=client; self.clock=clock
 def run_once(self,batch_id):
  batch=self.store.get_batch(batch_id)
  for task in self.store.list_due_tasks(batch_id,self.clock()):
   self.store.mark_submitting(batch_id,task['task_id'])
   try:
    result=self.client.submit(batch_id=batch_id,task=task)
    self.store.record_submission(batch_id,task['task_id'],result['job_id'])
   except BatchCredentialError: raise
   except Exception as exc: self.store.mark_error(batch_id,task['task_id'],exc)
  for task in self.store.list_tasks(batch_id):
   if task['state'] not in ('submitted','running','downloading') or not task['remote_job_id']: continue
   try:
    status=self.client.status(task['remote_job_id']); remote=status['status']
    if remote in ('pending','running'):
     self.store.record_remote_status(batch_id,task['task_id'],remote); continue
    if remote in ('failed','interrupted'):
     self.store.record_remote_status(batch_id,task['task_id'],remote); continue
    if remote!='completed': raise RuntimeError('unknown remote report status')
    self.store.mark_downloading(batch_id,task['task_id'])
    path=publish_docx(batch['output_root'],task['task_id'],task['filename'],self.client.download(task['remote_job_id']))
    self.store.mark_downloaded(batch_id,task['task_id'],path)
   except BatchCredentialError: raise
   except Exception as exc: self.store.mark_error(batch_id,task['task_id'],exc)
  return self.status(batch_id)
 def status(self,batch_id): return {'batch':self.store.get_batch(batch_id),'tasks':self.store.list_tasks(batch_id)}
