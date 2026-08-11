"""Staff-only auth models — patients never authenticate (see session_models)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class TokenPayload(BaseModel):
    sub: str
    username: str
    role: str
    iat: int
    exp: int


class UserInfo(BaseModel):
    user_id: str
    username: str
    role: str
    is_active: bool
    last_login: float | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=200)
    role: str = "staff"


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None
