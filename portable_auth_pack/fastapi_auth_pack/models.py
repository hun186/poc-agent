from __future__ import annotations

from pydantic import BaseModel, Field


class AuthPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    full_name: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class ApprovePayload(BaseModel):
    role: str = Field(...)
