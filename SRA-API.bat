cd /d D:\shared\TopicClassification\poc-agent && ^
set PYTHONUNBUFFERED=1 && ^
uvicorn api.main:app --host 0.0.0.0 --port 9002 2>&1 | ^
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\shared\TopicClassification\poc-agent\SRA-LogRotate.ps1"
