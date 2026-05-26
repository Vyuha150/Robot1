"""Auth API — login, token refresh, user management."""

from __future__ import annotations

import logging
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bonbon_operator_api.auth.dependencies import get_current_user, require_permission
from bonbon_operator_api.models.auth_models import (
    LoginRequest,
    TokenPayload,
    TokenResponse,
    UserCreate,
    UserInfo,
    UserUpdate,
)
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["authentication"])


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_router.post("/login", response_model=APIResponse)
async def login(request: Request, body: LoginRequest) -> APIResponse:
    """Authenticate with username/password and receive a JWT."""
    auth_mgr = request.app.state.auth_manager
    audit = request.app.state.audit_logger
    metrics = request.app.state.metrics
    ip = request.client.host if request.client else ""

    t0 = time.monotonic()
    user = auth_mgr.authenticate(body.username, body.password)

    if not user:
        metrics.record_auth(success=False)
        audit.log(
            actor_id="anonymous",
            actor_name=body.username,
            actor_role="unknown",
            action="auth:login",
            outcome="failure",
            detail="Invalid credentials",
            ip_address=ip,
            duration_ms=(time.monotonic() - t0) * 1000,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token, expires_in = auth_mgr.create_token(user)
    metrics.record_auth(success=True)
    audit.log(
        actor_id=user["user_id"],
        actor_name=user["username"],
        actor_role=user["role"],
        action="auth:login",
        outcome="success",
        ip_address=ip,
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    metrics.record_audit_event()
    return APIResponse.ok(TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
        role=user["role"],
    ))


# ---------------------------------------------------------------------------
# Current user info
# ---------------------------------------------------------------------------

@auth_router.get("/me", response_model=APIResponse)
async def get_me(
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
) -> APIResponse:
    """Return info about the currently authenticated user."""
    auth_mgr = request.app.state.auth_manager
    user = auth_mgr.get_user_by_id(current_user.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse.ok(UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
        is_active=bool(user["is_active"]),
        last_login=user.get("last_login"),
    ))


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

@auth_router.get("/users", response_model=APIResponse)
async def list_users(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    """List all users (admin only)."""
    auth_mgr = request.app.state.auth_manager
    users = auth_mgr.list_users()
    return APIResponse.ok([
        UserInfo(
            user_id=u["user_id"],
            username=u["username"],
            role=u["role"],
            is_active=bool(u["is_active"]),
            last_login=u.get("last_login"),
        )
        for u in users
    ])


@auth_router.post("/users", response_model=APIResponse, status_code=201)
async def create_user(
    request: Request,
    body: UserCreate,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    """Create a new user (admin only)."""
    auth_mgr = request.app.state.auth_manager
    audit = request.app.state.audit_logger
    ip = request.client.host if request.client else ""
    try:
        user = auth_mgr.create_user(body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit.log(
        actor_id=current_user.sub,
        actor_name=current_user.username,
        actor_role=current_user.role,
        action="user:create",
        target=user.user_id,
        request_data={"username": body.username, "role": body.role},
        outcome="success",
        ip_address=ip,
    )
    request.app.state.metrics.record_audit_event()
    return APIResponse.ok(user)


@auth_router.patch("/users/{user_id}", response_model=APIResponse)
async def update_user(
    request: Request,
    user_id: str,
    body: UserUpdate,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    """Update a user's role, active state, or password (admin only)."""
    auth_mgr = request.app.state.auth_manager
    audit = request.app.state.audit_logger
    ip = request.client.host if request.client else ""
    try:
        updated = auth_mgr.update_user(user_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    audit.log(
        actor_id=current_user.sub,
        actor_name=current_user.username,
        actor_role=current_user.role,
        action="user:update",
        target=user_id,
        outcome="success",
        ip_address=ip,
    )
    request.app.state.metrics.record_audit_event()
    return APIResponse.ok(updated)


@auth_router.delete("/users/{user_id}", response_model=APIResponse)
async def delete_user(
    request: Request,
    user_id: str,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    """Delete a user (admin only)."""
    if user_id == current_user.sub:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    auth_mgr = request.app.state.auth_manager
    audit = request.app.state.audit_logger
    ip = request.client.host if request.client else ""
    deleted = auth_mgr.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    audit.log(
        actor_id=current_user.sub,
        actor_name=current_user.username,
        actor_role=current_user.role,
        action="user:delete",
        target=user_id,
        outcome="success",
        ip_address=ip,
    )
    request.app.state.metrics.record_audit_event()
    return APIResponse.ok({"deleted": True, "user_id": user_id})
