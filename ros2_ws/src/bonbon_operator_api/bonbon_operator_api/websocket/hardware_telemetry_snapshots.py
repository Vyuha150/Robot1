"""Snapshot builder for the "hardware-telemetry" WebSocket channel.

Same relay pattern as websocket/edge_ai_snapshots.py: hardware_telemetry_node
is a real, persistent process (on whichever Pi it runs -- see that
node's pi_role gating) that owns state a freshly constructed object on
Pi-1 could never honestly reproduce (live wheel/joint/battery readings,
per-Pi resource samples). This relays the REAL state
hardware_telemetry_node published on /bonbon/hardware_telemetry/status,
cached by ros2_bridge.py's get_hardware_telemetry_snapshot(). Honestly
reports unavailable when no message has been received yet -- never
fabricates a zero-state as if it were real hardware activity.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def hardware_telemetry_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = getattr(app.state, "ros2_bridge", None)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    snapshot = bridge.get_hardware_telemetry_snapshot()
    if snapshot is None:
        return {
            "available": False,
            "message": "no hardware_telemetry_node message received yet on "
            "/bonbon/hardware_telemetry/status -- the node may not be running, "
            "or hasn't published its first tick yet",
        }
    return {"available": True, **snapshot}


# channel name -> snapshot builder, merged into status_broadcasters.CHANNEL_SNAPSHOTS
HARDWARE_TELEMETRY_CHANNEL_SNAPSHOTS = {
    "hardware-telemetry": hardware_telemetry_snapshot,
}
