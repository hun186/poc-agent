from pathlib import Path
import os, re, tempfile, zipfile
class InvalidDocxError(ValueError): pass

def output_path(root,task_id,filename=None):
 root=Path(root).resolve(); root.mkdir(parents=True,exist_ok=True)
 requested=Path(str(filename or '') .replace('\\','/')).name if filename else ''
 stem=Path(requested).stem if requested else task_id
 stem=re.sub(r'[^\w.-]+','_',stem,flags=re.UNICODE).strip('._') or 'report'
 safe_id=re.sub(r'[^\w.-]+','_',task_id,flags=re.UNICODE).strip('._') or 'task'
 path=(root/f'{safe_id}-{stem}.docx').resolve()
 try:path.relative_to(root)
 except ValueError as exc: raise ValueError('output path escapes root') from exc
 return path

def publish_docx(root,task_id,filename,data):
 final=output_path(root,task_id,filename)
 fd,tmp=tempfile.mkstemp(prefix='.'+final.name+'.',suffix='.tmp',dir=final.parent)
 try:
  with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
  if not zipfile.is_zipfile(tmp): raise InvalidDocxError('download is not a valid DOCX container')
  with zipfile.ZipFile(tmp) as z:
   if '[Content_Types].xml' not in z.namelist() or 'word/document.xml' not in z.namelist(): raise InvalidDocxError('download is not a valid DOCX document')
  if final.exists(): raise FileExistsError(f'output already exists: {final.name}')
  os.replace(tmp,final)
  try:
   dfd=os.open(final.parent,os.O_RDONLY); os.fsync(dfd); os.close(dfd)
  except OSError: pass
  return final
 finally:
  try: os.unlink(tmp)
  except FileNotFoundError: pass
