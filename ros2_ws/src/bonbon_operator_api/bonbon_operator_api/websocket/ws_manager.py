"""WebSocketConnectionManager — channel-based broadcast hub.

Each client subscribes to one or more named channels.
Sending to a channel delivers to all connected clients subscribed to it.

Channels
--------
* ``robot-status``      — periodic full status snapshot (~1 Hz)
* ``safety-events``     — immediate safety state changes
* ``navigation-events`` — navigation goal / progress updates
* ``diagnostics``       — module health updates
* ``live-logs``         — log stream (engineer+ only)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional, Set

from fastapi import WebSocket

from bonbon_operator_api.models.response_models import WSMessage

logger = logging.getLogger(__name__)

# Per-user maximum concurrent WebSocket connections
_MAX_CONNECTIONS_PER_USER = 5

# Valid channel names
VALID_CHANNELS: Set[str] = {
    "robot-status",
    "safety-events",
    "navigation-events",
    "diagnostics",
    "live-logs",
}


class WebSocketConnectionManager:
    """Manage WebSocket connections grouped by channel.

    Thread safety: all methods are async and called from the same event loop.
    """

    def __init__(self) -> None:
        # channel -> {websocket: user_id}
        self._channels: Dict[str, Dict[WebSocket, str]] = {
            ch: {} for ch in VALID_CHANNELS
        }
        # user_id -> count of open connections
        self._user_conn_count: Dict[str, int] = {}
        # websocket -> set of subscribed channels (for cleanup)
        self._ws_channels: Dict[WebSocket, Set[str]] = {}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(
        self,
        websocket: WebSocket,
        channel: str,
        user_id: str,
    ) -> None:
        """Accept and register a new WebSocket connection on *channel*.

        Raises ``ValueError`` for unknown channels or connection limit exceeded.
        """
        if channel not in VALID_CHANNELS:
            await websocket.close(code=4004, reason=f"Unknown channel: {channel}")
            raise ValueError(f"Unknown channel: {channel}")

        count = self._user_conn_count.get(user_id, 0)
        if count >= _MAX_CONNECTIONS_PER_USER:
            await websocket.close(
                code=4029,
                reason=f"Too many connections (max {_MAX_CONNECTIONS_PER_USER})",
            )
            raise ValueError("Connection limit exceeded")

        await websocket.accept()
        self._channels[channel][websocket] = user_id
        self._ws_channels.setdefault(websocket, set()).add(channel)
        self._user_conn_count[user_id] = count + 1
        logger.debug(
            "WS connected: user=%s channel=%s total_on_channel=%d",
            user_id, channel, len(self._channels[channel]),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from all channels it was subscribed to."""
        channels = self._ws_channels.pop(websocket, set())
        for channel in channels:
            user_id = self._channels[channel].pop(websocket, None)
            if user_id:
                count = self._user_conn_count.get(user_id, 0)
                if count > 1:
                    self._user_conn_count[user_id] = count - 1
                else:
                    self._user_conn_count.pop(user_id, None)
        logger.debug("WS disconnected from channels: %s", channels)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        channel: str,
        event: str,
        data,
        *,
        exclude_ws: Optional[WebSocket] = None,
    ) -> None:
        """Send a JSON message to all clients subscribed to *channel*."""
        if channel not in self._channels:
            return
        msg = WSMessage(
            channel=channel,
            event=event,
            data=data,
            timestamp=time.time(),
        )
        payload = msg.model_dump()
        dead: list = []
        for ws, user_id in list(self._channels[channel].items()):
            if ws is exclude_ws:
                continue
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.debug("WS send failed for user=%s: %s", user_id, exc)
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_all_channels(self, event: str, data) -> None:
        """Send to every connected client on every channel."""
        for channel in VALID_CHANNELS:
            await self.broadcast(channel, event, data)

    async def send_to_websocket(self, websocket: WebSocket, event: str, data) -> None:
        """Send a message to a single specific WebSocket."""
        msg = WSMessage(
            channel="direct",
            event=event,
            data=data,
            timestamp=time.time(),
        )
        try:
            await websocket.send_json(msg.model_dump())
        except Exception as exc:
            logger.debug("WS direct send failed: %s", exc)
            self.disconnect(websocket)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def connection_counts(self) -> Dict[str, int]:
        return {ch: len(conns) for ch, conns in self._channels.items()}

    def total_connections(self) -> int:
        return sum(len(c) for c in self._channels.values())
