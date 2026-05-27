"""Authentication and user management pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    role: str


class UserInfo(BaseModel):
    user_id: str
    username: str
    role: str
    is_active: bool
    last_login: float | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(viewer|operator|engineer|admin)$")


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(viewer|operator|engineer|admin)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class TokenPayload(BaseModel):
    """Decoded JWT payload."""

    sub: str  # user_id
    username: str
    role: str
    exp: int
    iat: int
