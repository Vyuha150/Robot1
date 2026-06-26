from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "founder": {"*"},
    "admin": {"*"},
    "manager": {"read", "write", "approve"},
    "employee": {"read", "task:update", "lead:update"},
    "viewer": {"read"},
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str | None) -> dict[str, str]:
    if not token:
        return {"sub": "demo-founder", "role": "founder"}
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc


def current_user(token: Annotated[str | None, Depends(oauth2_scheme)] = None) -> dict[str, str]:
    return decode_token(token)


def require_permission(permission: str):
    def dependency(user: Annotated[dict[str, str], Depends(current_user)]) -> dict[str, str]:
        role = user.get("role", "viewer")
        permissions = ROLE_PERMISSIONS.get(role, set())
        if "*" in permissions or permission in permissions or "write" in permissions:
            return user
        raise HTTPException(status_code=403, detail="Insufficient role permissions")

    return dependency
