"""WebSocket connection manager unit tests.

We test the manager in isolation (no live server needed).
Integration WS tests require an ASGI test client with WS support,
which we stub lightly here.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bonbon_operator_api.websocket.ws_manager import (
    WebSocketConnectionManager,
    VALID_CHANNELS,
)


# Scenario 1: Valid channels are defined
def test_valid_channels_non_empty():
    assert len(VALID_CHANNELS) >= 5
    assert "robot-status" in VALID_CHANNELS
    assert "safety-events" in VALID_CHANNELS


# Helper: create a mock websocket
def _mock_ws():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# Scenario 2: Connect to valid channel
@pytest.mark.asyncio
async def test_connect_valid_channel():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "user-1")
    ws.accept.assert_called_once()
    assert mgr.total_connections() == 1


# Scenario 3: Connect to invalid channel closes with 4004
@pytest.mark.asyncio
async def test_connect_invalid_channel_closes():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    with pytest.raises(ValueError):
        await mgr.connect(ws, "nonexistent-channel", "user-1")
    ws.close.assert_called_once()


# Scenario 4: Disconnect removes from manager
@pytest.mark.asyncio
async def test_disconnect_removes_connection():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "user-1")
    mgr.disconnect(ws)
    assert mgr.total_connections() == 0


# Scenario 5: Broadcast sends to subscribed clients
@pytest.mark.asyncio
async def test_broadcast_sends_to_subscribed():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "user-1")
    await mgr.broadcast("robot-status", "status_update", {"battery": 80})
    ws.send_json.assert_called_once()
    payload = ws.send_json.call_args[0][0]
    assert payload["event"] == "status_update"
    assert payload["channel"] == "robot-status"


# Scenario 6: Broadcast does not send to different channel subscribers
@pytest.mark.asyncio
async def test_broadcast_not_sent_to_wrong_channel():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "diagnostics", "user-1")
    await mgr.broadcast("robot-status", "status_update", {})
    ws.send_json.assert_not_called()


# Scenario 7: Connection count per channel
@pytest.mark.asyncio
async def test_connection_counts():
    mgr = WebSocketConnectionManager()
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    await mgr.connect(ws1, "robot-status", "user-1")
    await mgr.connect(ws2, "safety-events", "user-2")
    counts = mgr.connection_counts()
    assert counts["robot-status"] == 1
    assert counts["safety-events"] == 1


# Scenario 8: Per-user connection limit enforced
@pytest.mark.asyncio
async def test_per_user_connection_limit():
    mgr = WebSocketConnectionManager()
    wss = [_mock_ws() for _ in range(5)]
    for i, ws in enumerate(wss):
        await mgr.connect(ws, "robot-status", "heavy-user")
    # 6th connection should fail
    ws_extra = _mock_ws()
    with pytest.raises(ValueError):
        await mgr.connect(ws_extra, "robot-status", "heavy-user")


# Scenario 9: Failed send auto-disconnects client
@pytest.mark.asyncio
async def test_failed_send_disconnects():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    ws.send_json.side_effect = Exception("connection dropped")
    await mgr.connect(ws, "robot-status", "user-1")
    await mgr.broadcast("robot-status", "update", {})
    assert mgr.total_connections() == 0


# Scenario 10: Disconnect decrements user connection count
@pytest.mark.asyncio
async def test_disconnect_decrements_count():
    mgr = WebSocketConnectionManager()
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    await mgr.connect(ws1, "robot-status", "user-1")
    await mgr.connect(ws2, "safety-events", "user-1")
    assert mgr._user_conn_count.get("user-1", 0) == 2
    mgr.disconnect(ws1)
    assert mgr._user_conn_count.get("user-1", 0) == 1


# Scenario 11: Broadcast excludes specified websocket
@pytest.mark.asyncio
async def test_broadcast_exclude_ws():
    mgr = WebSocketConnectionManager()
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    await mgr.connect(ws1, "robot-status", "user-1")
    await mgr.connect(ws2, "robot-status", "user-2")
    await mgr.broadcast("robot-status", "update", {}, exclude_ws=ws1)
    ws1.send_json.assert_not_called()
    ws2.send_json.assert_called_once()


# Scenario 12: send_to_websocket delivers direct message
@pytest.mark.asyncio
async def test_send_to_websocket_direct():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "user-1")
    await mgr.send_to_websocket(ws, "pong", {"ts": 1234})
    ws.send_json.assert_called_once()
    payload = ws.send_json.call_args[0][0]
    assert payload["event"] == "pong"


# Scenario 13: Manager starts with zero connections
def test_initial_zero_connections():
    mgr = WebSocketConnectionManager()
    assert mgr.total_connections() == 0


# Scenario 14: Connection counts dict has all channels
def test_connection_counts_all_channels():
    mgr = WebSocketConnectionManager()
    counts = mgr.connection_counts()
    for ch in VALID_CHANNELS:
        assert ch in counts


# Scenario 15: Multiple broadcasts to same channel
@pytest.mark.asyncio
async def test_multiple_broadcasts():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "user-1")
    for i in range(5):
        await mgr.broadcast("robot-status", f"event_{i}", {"i": i})
    assert ws.send_json.call_count == 5


# Scenario 16: Disconnect non-existent ws is safe
def test_disconnect_nonexistent_ws_safe():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    # Should not raise
    mgr.disconnect(ws)


# Scenario 17: User count removed when all connections closed
@pytest.mark.asyncio
async def test_user_count_removed_after_all_disconnect():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "solo-user")
    mgr.disconnect(ws)
    assert "solo-user" not in mgr._user_conn_count


# Scenario 18: broadcast_all_channels sends to every channel subscriber
@pytest.mark.asyncio
async def test_broadcast_all_channels():
    mgr = WebSocketConnectionManager()
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    await mgr.connect(ws1, "robot-status", "user-1")
    await mgr.connect(ws2, "safety-events", "user-2")
    await mgr.broadcast_all_channels("shutdown", {"reason": "reboot"})
    ws1.send_json.assert_called()
    ws2.send_json.assert_called()


# Scenario 19: Same user can connect to different channels
@pytest.mark.asyncio
async def test_same_user_multiple_channels():
    mgr = WebSocketConnectionManager()
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    await mgr.connect(ws1, "robot-status", "multi-user")
    await mgr.connect(ws2, "safety-events", "multi-user")
    assert mgr._user_conn_count["multi-user"] == 2


# Scenario 20: WSMessage payload has correct structure
@pytest.mark.asyncio
async def test_ws_message_structure():
    mgr = WebSocketConnectionManager()
    ws = _mock_ws()
    await mgr.connect(ws, "robot-status", "user-1")
    await mgr.broadcast("robot-status", "test_event", {"key": "val"})
    payload = ws.send_json.call_args[0][0]
    assert "channel" in payload
    assert "event" in payload
    assert "data" in payload
    assert "timestamp" in payload
