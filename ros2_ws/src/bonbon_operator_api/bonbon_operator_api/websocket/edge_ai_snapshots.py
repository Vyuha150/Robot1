"""Snapshot builders for the 6 new Edge AI Runtime WebSocket channels
(edge-ai-status, edge-ai-models, edge-ai-routes, edge-ai-resources,
edge-ai-safety, edge-ai-cache), Edge AI Runtime brief Phase 12.

Unlike ai_model_snapshots.py's functions (which construct a fresh
ModelDashboardPublisher every call -- honest because that state is
cheaply/correctly recomputable from static config), 5 of these 6
channels carry STATE that only the real, persistent edge_ai_runtime_node
process on Pi-2 has (accumulated safety-block counts, cache hit rates,
live CPU/thermal readings, in-flight route decisions) -- a freshly
constructed EdgeAIDashboardPublisher on Pi-1 would always show an empty/
zeroed snapshot regardless of what's actually happening on the AI Pi,
which would be misleading even though technically not fabricated.

So these relay the REAL state edge_ai_runtime_node published on
/bonbon/edge_ai/<channel>, cached by ros2_bridge.py's
get_edge_ai_snapshot(). Honestly reports unavailable when no message has
been received yet -- never fabricates a zero-state as if it were real
Pi-2 activity.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def _relay(app: FastAPI, channel: str) -> dict[str, Any]:
    bridge = getattr(app.state, "ros2_bridge", None)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    snapshot = bridge.get_edge_ai_snapshot(channel)
    if snapshot is None:
        return {
            "available": False,
            "message": f"no edge_ai_runtime_node message received yet on /bonbon/edge_ai/{channel} "
            "-- the node may not be running on Pi-2, or hasn't published its first tick yet",
        }
    return {"available": True, **snapshot}


def edge_ai_status_snapshot(app: FastAPI) -> dict[str, Any]:
    return _relay(app, "status")


def edge_ai_models_snapshot(app: FastAPI) -> dict[str, Any]:
    return _relay(app, "models")


def edge_ai_routes_snapshot(app: FastAPI) -> dict[str, Any]:
    return _relay(app, "routes")


def edge_ai_resources_snapshot(app: FastAPI) -> dict[str, Any]:
    return _relay(app, "resources")


def edge_ai_safety_snapshot(app: FastAPI) -> dict[str, Any]:
    return _relay(app, "safety")


def edge_ai_cache_snapshot(app: FastAPI) -> dict[str, Any]:
    return _relay(app, "cache")


# channel name -> snapshot builder, merged into status_broadcasters.CHANNEL_SNAPSHOTS
EDGE_AI_CHANNEL_SNAPSHOTS = {
    "edge-ai-status": edge_ai_status_snapshot,
    "edge-ai-models": edge_ai_models_snapshot,
    "edge-ai-routes": edge_ai_routes_snapshot,
    "edge-ai-resources": edge_ai_resources_snapshot,
    "edge-ai-safety": edge_ai_safety_snapshot,
    "edge-ai-cache": edge_ai_cache_snapshot,
}
