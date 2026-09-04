import json
from batch_scheduler.cli import main

def test_validate_and_import_status(tmp_path,monkeypatch,capsys):
 p=tmp_path/'i.json';p.write_text(json.dumps([{'task_id':'t','prompt':'p'}]));assert main(['validate',str(p)])==0
 monkeypatch.setenv('SRA_BATCH_DB_PATH',str(tmp_path/'db')); monkeypatch.setenv('SRA_BATCH_OUTPUT_ROOT',str(tmp_path/'out'))
 assert main(['import',str(p),'--batch-id','b','--output-dir',str(tmp_path/'out')])==0
 assert main(['status','b','--json'])==0; out=capsys.readouterr().out; assert 'SRA_BATCH_SERVICE_KEY' not in out and '"task_id": "t"' in out
