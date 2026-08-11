"""FastAPI dependency injection for staff auth and patient session validation."""

from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bonbon_patient_kiosk.models.auth_models import TokenPayload

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


def _get_auth_manager(request: Request):
    return request.app.state.auth_manager


def _get_role_manager(request: Request):
    return request.app.state.role_manager


async def get_current_staff_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenPayload:
    """Validate a staff Bearer token. Raises 401 on missing/invalid/expired token."""
    auth_manager = _get_auth_manager(request)
    token = credentials.credentials if credentials else request.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = auth_manager.decode_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        logger.debug("Invalid token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user = auth_manager.get_user_by_id(payload.sub)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User account is inactive or does not exist")
    return payload


def require_permission(permission: str):
    async def _check(
        request: Request,
        current_user: TokenPayload = Depends(get_current_staff_user),
    ) -> TokenPayload:
        role_mgr = _get_role_manager(request)
        if not role_mgr.has_permission(current_user.role, permission):
            logger.warning(
                "Permission denied: user=%s role=%s required=%s path=%s",
                current_user.username,
                current_user.role,
                permission,
                request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {permission}",
            )
        return current_user

    return _check


def require_session(request: Request, session_id: str):
    """Validate a patient session id exists and is not expired.

    Raises 404 rather than 401 -- there is no "wrong password" concept for
    an anonymous kiosk session, just "this session no longer exists."
    """
    session_store = request.app.state.session_store
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    return session
