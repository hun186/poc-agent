import csv,json
from datetime import datetime
import pytest
from openpyxl import Workbook
from batch_scheduler.input_loader import load_batch
from batch_scheduler.models import BatchValidationError

def test_formats_normalize_equivalently(tmp_path):
 rows=[{'task_id':'a','prompt':'hello','scheduled_at':'2026-09-04T08:00:00+08:00','metadata_json':'{"x":1}'},{'task_id':'b','prompt':'world','scheduled_at':'','metadata_json':''}]
 csvp=tmp_path/'x.csv';
 with csvp.open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 jp=tmp_path/'x.json'; jp.write_text(json.dumps([{'task_id':r['task_id'],'prompt':r['prompt'],'scheduled_at':r['scheduled_at'],'metadata':json.loads(r['metadata_json']) if r['metadata_json'] else {}} for r in rows]))
 xp=tmp_path/'x.xlsx'; wb=Workbook(); ws=wb.active; ws.append(list(rows[0])); [ws.append(list(r.values())) for r in rows]; wb.save(xp)
 loaded=[load_batch(x).tasks for x in (csvp,jp,xp)]
 assert loaded[0]==loaded[1]==loaded[2]
@pytest.mark.parametrize('obj',[ [{'task_id':'x','prompt':'a'},{'task_id':'x','prompt':'b'}], [{'task_id':'','prompt':'a'}], [{'task_id':'x','prompt':' '}], [{'task_id':'x','prompt':'a','wat':1}], [{'task_id':'x','prompt':'a','scheduled_at':'2026-01-01T00:00:00'}]])
def test_invalid_json_tasks(tmp_path,obj):
 p=tmp_path/'x.json';p.write_text(json.dumps(obj))
 with pytest.raises(BatchValidationError): load_batch(p)
def test_reject_xls(tmp_path):
 p=tmp_path/'x.xls';p.write_bytes(b'x')
 with pytest.raises(BatchValidationError):load_batch(p)
