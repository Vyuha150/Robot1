"""WebSocket route handlers.

URL pattern:  ws://<host>/ws/{channel}?token=<jwt>

Channels:
  robot-status       — full status snapshot, broadcast ~1 Hz from background task
  safety-events      — safety state changes (immediate)
  navigation-events  — navigation goal and progress updates
  diagnostics        — module health / log events
  live-logs          — raw log stream (engineer+ only)

Auth: Bearer token passed as ?token= query param (browser WS limitation).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from bonbon_operator_api.auth.dependencies import _get_auth_manager, _get_role_manager
from bonbon_operator_api.websocket.ws_manager import WebSocketConnectionManager, VALID_CHANNELS

logger = logging.getLogger(__name__)

# Roles required per channel
_CHANNEL_MIN_PERMISSION = {
    "robot-status":      "robot:read",
    "safety-events":     "robot:read",
    "navigation-events": "robot:read",
    "diagnostics":       "diagnostics:read",
    "live-logs":         "diagnostics:read",
}

ws_router = APIRouter(prefix="/ws", tags=["websocket"])


def _authenticate_ws(request_scope, token: Optional[str]) -> Optional[dict]:
    """Validate WS token; return decoded payload dict or None."""
    if not token:
        return None
    # app is accessible via scope["app"]
    app = request_scope.get("app")
    if not app:
        return None
    try:
        auth_mgr = app.state.auth_manager
        payload = auth_mgr.decode_token(token)
        user = auth_mgr.get_user_by_id(payload.sub)
        if not user or not user["is_active"]:
            return None
        return {"sub": payload.sub, "username": payload.username, "role": payload.role}
    except jwt.ExpiredSignatureError:
        logger.debug("WS token expired")
        return None
    except Exception as exc:
        logger.debug("WS token invalid: %s", exc)
        return None


def _check_channel_permission(role: str, channel: str, role_mgr) -> bool:
    required = _CHANNEL_MIN_PERMISSION.get(channel, "robot:read")
    return role_mgr.has_permission(role, required)


@ws_router.websocket("/{channel}")
async def websocket_channel(
    websocket: WebSocket,
    channel: str,
    token: Optional[str] = Query(default=None),
) -> None:
    """Connect to a named event channel."""
    app = websocket.app

    # 1. Auth
    user = _authenticate_ws(websocket.scope, token)
    if not user:
        await websocket.close(code=4001, reason="Not authenticated")
        return

    # 2. Channel exists
    if channel not in VALID_CHANNELS:
        await websocket.close(code=4004, reason=f"Unknown channel: {channel}")
        return

    # 3. Permission
    role_mgr = app.state.role_manager
    if not _check_channel_permission(user["role"], channel, role_mgr):
        await websocket.close(code=4003, reason="Insufficient permissions")
        return

    # 4. Register
    ws_mgr: WebSocketConnectionManager = app.state.ws_manager
    try:
        await ws_mgr.connect(websocket, channel, user["sub"])
    except ValueError as exc:
        # connect() already closed the websocket
        logger.warning("WS connect refused for user=%s: %s", user["username"], exc)
        return

    # 5. Send initial welcome
    try:
        await ws_mgr.send_to_websocket(websocket, "connected", {
            "channel": channel,
            "user": user["username"],
            "role": user["role"],
            "server_time": time.time(),
        })
    except Exception:
        ws_mgr.disconnect(websocket)
        return

    # 6. Keep alive — wait for disconnect or ping/pong
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
                # Handle ping
                if isinstance(data, dict) and data.get("type") == "ping":
                    await ws_mgr.send_to_websocket(websocket, "pong",
                                                   {"ts": time.time()})
            except asyncio.TimeoutError:
                # Send server-side keepalive ping
                await ws_mgr.send_to_websocket(websocket, "ping",
                                               {"ts": time.time()})
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS loop error user=%s: %s", user["username"], exc)
    finally:
        ws_mgr.disconnect(websocket)
        logger.debug("WS disconnected: user=%s channel=%s", user["username"], channel)
