from __future__ import annotations

from fastapi import Depends, FastAPI

from fastapi_auth_pack import AuthUser, current_user, require_data_editor, require_db_operator, require_superuser, router as auth_router

app = FastAPI(title="FastAPI Auth Pack Demo")
app.include_router(auth_router)


@app.get("/v1/private/ping")
def private_ping(user: AuthUser = Depends(current_user)) -> dict[str, str]:
    return {"message": f"hello {user.username}"}


@app.post("/v1/documents/ping")
def editor_ping(user: AuthUser = Depends(require_data_editor)) -> dict[str, str]:
    return {"message": f"editor hello {user.username}"}


@app.post("/v1/database/ping")
def database_ping(user: AuthUser = Depends(require_db_operator)) -> dict[str, str]:
    return {"message": f"database hello {user.username}"}


@app.get("/v1/admin/ping")
def admin_ping(user: AuthUser = Depends(require_superuser)) -> dict[str, str]:
    return {"message": f"admin hello {user.username}"}
