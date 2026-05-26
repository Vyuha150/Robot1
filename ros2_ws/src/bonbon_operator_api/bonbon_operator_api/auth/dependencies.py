"""FastAPI dependency injection for authentication and authorization."""

from __future__ import annotations

import logging
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bonbon_operator_api.models.auth_models import TokenPayload

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


def _get_auth_manager(request: Request):
    """Extract AuthManager from app state."""
    return request.app.state.auth_manager


def _get_role_manager(request: Request):
    """Extract RolePermissionManager from app state."""
    return request.app.state.role_manager


def _get_audit_logger(request: Request):
    """Extract AuditLogger from app state."""
    return request.app.state.audit_logger


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> TokenPayload:
    """Dependency: validate Bearer token and return decoded payload.

    Raises HTTP 401 on missing/invalid/expired token.
    """
    auth_manager = _get_auth_manager(request)

    # Try header first, then query param (for WebSocket compatibility)
    token: Optional[str] = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = auth_manager.decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        logger.debug("Invalid token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user still active in DB
    user = auth_manager.get_user_by_id(payload.sub)
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or does not exist",
        )
    return payload


def require_permission(permission: str):
    """Return a FastAPI dependency that enforces *permission* for the caller."""

    async def _check(
        request: Request,
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        role_mgr = _get_role_manager(request)
        if not role_mgr.has_permission(current_user.role, permission):
            logger.warning(
                "Permission denied: user=%s role=%s required=%s path=%s",
                current_user.username, current_user.role, permission, request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {permission}",
            )
        return current_user

    return _check
