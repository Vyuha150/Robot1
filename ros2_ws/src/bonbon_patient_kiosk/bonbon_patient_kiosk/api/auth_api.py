"""Staff auth — login, current user, user management (admin only).

Scoped-down copy of bonbon_operator_api's auth_api: two roles instead of
four, no metrics collector dependency (this kiosk doesn't need one).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bonbon_patient_kiosk.auth.dependencies import get_current_staff_user, require_permission
from bonbon_patient_kiosk.models.auth_models import (
    LoginRequest,
    TokenPayload,
    TokenResponse,
    UserCreate,
    UserInfo,
    UserUpdate,
)
from bonbon_patient_kiosk.models.response_models import APIResponse

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["staff-authentication"])


@auth_router.post("/login", response_model=APIResponse)
async def login(request: Request, body: LoginRequest) -> APIResponse:
    auth_mgr = request.app.state.auth_manager
    audit = request.app.state.audit_logger
    ip = request.client.host if request.client else ""

    user = auth_mgr.authenticate(body.username, body.password)
    if not user:
        audit.log(
            actor_id="anonymous",
            actor_role="unknown",
            action="auth:login",
            outcome="failure",
            ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token, expires_in = auth_mgr.create_token(user)
    audit.log(actor_id=user["user_id"], actor_role=user["role"], action="auth:login", outcome="success", ip_address=ip)
    return APIResponse.ok(
        TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in, role=user["role"])
    )


@auth_router.get("/me", response_model=APIResponse)
async def get_me(
    request: Request, current_user: TokenPayload = Depends(get_current_staff_user)
) -> APIResponse:
    auth_mgr = request.app.state.auth_manager
    user = auth_mgr.get_user_by_id(current_user.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse.ok(
        UserInfo(
            user_id=user["user_id"],
            username=user["username"],
            role=user["role"],
            is_active=bool(user["is_active"]),
            last_login=user.get("last_login"),
        )
    )


@auth_router.get("/users", response_model=APIResponse)
async def list_users(
    request: Request, current_user: TokenPayload = Depends(require_permission("user:manage"))
) -> APIResponse:
    users = request.app.state.auth_manager.list_users()
    return APIResponse.ok(
        [
            UserInfo(
                user_id=u["user_id"],
                username=u["username"],
                role=u["role"],
                is_active=bool(u["is_active"]),
                last_login=u.get("last_login"),
            )
            for u in users
        ]
    )


@auth_router.post("/users", response_model=APIResponse, status_code=201)
async def create_user(
    request: Request,
    body: UserCreate,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    try:
        user = request.app.state.auth_manager.create_user(body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    request.app.state.audit_logger.log(
        actor_id=current_user.sub,
        actor_role=current_user.role,
        action="user:create",
        target=user.user_id,
        outcome="success",
        request_data={"username": body.username, "role": body.role},
    )
    return APIResponse.ok(user)


@auth_router.patch("/users/{user_id}", response_model=APIResponse)
async def update_user(
    request: Request,
    user_id: str,
    body: UserUpdate,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    try:
        updated = request.app.state.auth_manager.update_user(user_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    request.app.state.audit_logger.log(
        actor_id=current_user.sub, actor_role=current_user.role, action="user:update", target=user_id, outcome="success"
    )
    return APIResponse.ok(updated)


@auth_router.delete("/users/{user_id}", response_model=APIResponse)
async def delete_user(
    request: Request,
    user_id: str,
    current_user: TokenPayload = Depends(require_permission("user:manage")),
) -> APIResponse:
    if user_id == current_user.sub:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    deleted = request.app.state.auth_manager.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    request.app.state.audit_logger.log(
        actor_id=current_user.sub, actor_role=current_user.role, action="user:delete", target=user_id, outcome="success"
    )
    return APIResponse.ok({"deleted": True, "user_id": user_id})
