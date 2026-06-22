# api/main.py
# cd D:\shared\TopicClassification\poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 9002
# cd /mntCZJ/TopicClassification/poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 9002
# http://192.168.0.228:9002/v1
# http://192.168.0.133:9002/v1

#cd D:\shared\TopicClassification\poc-agent&&python -m api.run_api --public --ssl --port 9002
#cd /mntCZJ/TopicClassification/poc-agent&&python -m api.run_api --public --port 9002

from api.core.proctitle import init_proctitle

# 啟動時先設定 process title
init_proctitle(app_name="SRA-API")

from fastapi import FastAPI  # , HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from api.routers import chat, docs, export, editor, excel_to_sql

app = FastAPI(
    title="SRA-Structured Retrieval Agent (OpenAI-compatible)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/editor")


app.include_router(chat.router)
app.include_router(docs.router)
app.include_router(export.router)
app.include_router(editor.router)
app.include_router(excel_to_sql.router)
