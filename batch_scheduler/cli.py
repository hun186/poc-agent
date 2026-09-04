import argparse,json,sys,time,uuid
from .config import BatchSchedulerConfig
from .input_loader import load_batch
from .store import BatchSchedulerStore
from .sra_client import SRAReportJobClient,BatchCredentialError
from .service import BatchSchedulerService

def parser():
 p=argparse.ArgumentParser(prog='batch-scheduler'); sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('validate').add_argument('input')
 for name in ('import','execute'):
  q=sub.add_parser(name); q.add_argument('input'); q.add_argument('--batch-id',required=True); q.add_argument('--output-dir',required=True)
 for name in ('run','resume'):
  q=sub.add_parser(name); q.add_argument('batch_id'); q.add_argument('--once',action='store_true')
 q=sub.add_parser('status'); q.add_argument('batch_id'); q.add_argument('--json',action='store_true')
 return p

def main(argv=None):
 try:
  a=parser().parse_args(argv)
  if a.command=='validate':
   loaded=load_batch(a.input); print(json.dumps({'valid':True,'tasks':len(loaded.tasks)})); return 0
  cfg=BatchSchedulerConfig.from_env(require_key=a.command in ('run','resume','execute'))
  store=BatchSchedulerStore(cfg.db_path); store.initialize()
  if a.command in ('import','execute'):
   loaded=load_batch(a.input); store.import_batch(loaded,a.batch_id,a.output_dir)
   if a.command=='import': print(a.batch_id); return 0
  service=BatchSchedulerService(store,SRAReportJobClient(cfg))
  batch_id=a.batch_id
  if a.command=='status':
   data=service.status(batch_id); print(json.dumps(data,ensure_ascii=False,default=str) if a.json else '\n'.join(f"{x['task_id']}: {x['state']}" for x in data['tasks'])); return 0
  while True:
   data=service.run_once(batch_id)
   states={x['state'] for x in data['tasks']}
   if states <= {'downloaded','report_failed','interrupted','error'} or getattr(a,'once',False): break
   time.sleep(cfg.poll_seconds)
  print(json.dumps(data,ensure_ascii=False,default=str)); return 0 if states=={'downloaded'} else 3
 except BatchCredentialError as exc: print(str(exc),file=sys.stderr); return 4
 except (ValueError,KeyError,OSError) as exc: print(str(exc),file=sys.stderr); return 2
 except Exception as exc: print(str(exc),file=sys.stderr); return 1
