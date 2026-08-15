"""Snapshot builders for the 6 new perception WebSocket channels
(perception-objects, perception-people, perception-affective,
perception-gestures, perception-human-state, perception-efficiency) --
Dashboard Perception Gap Report Phase 8.

Every one of these categories was previously invisible to an operator: the
ROS2 bridge subscribed only to PersonTrack and PerceptionEfficiencyMetrics,
and the frontend's "Perception"/"Affective AI"/"Gesture" tabs rendered a
browser-side COCO-SSD demo unrelated to the robot. See
docs/DASHBOARD_PERCEPTION_GAP_REPORT.md.

Follows the exact "no fake PASS" pattern already established for
boot-topology/AI-runtime/Pi-efficiency and edge_ai_snapshots.py: relay the
real state ros2_bridge.py cached from live topics, honestly report
`available: False` when nothing has been received yet, never fabricate a
zero-state as if it were real activity.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def _bridge(app: FastAPI):
    return getattr(app.state, "ros2_bridge", None)


def perception_objects_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = _bridge(app)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    objects, meta = bridge.get_perception_objects()
    if meta is None:
        return {
            "available": False,
            "message": "no DetectedObjectArray received yet on /bonbon/vision/objects",
        }
    return {"available": True, "objects": list(objects.values()), "meta": meta}


def perception_people_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = _bridge(app)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    people = bridge.get_perception_people()
    if not people:
        return {
            "available": False,
            "message": "no PersonTrack received yet on /bonbon/persons/tracks, "
            "or nobody is currently in the scene",
            "people": [],
        }
    return {"available": True, "people": list(people.values())}


def perception_gestures_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = _bridge(app)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    gestures = bridge.get_perception_gestures()
    if not gestures:
        return {
            "available": False,
            "message": "no GestureEvent received yet on /bonbon/gesture/events",
            "gestures": [],
        }
    return {"available": True, "gestures": gestures}


def perception_affective_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = _bridge(app)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    affective = bridge.get_perception_affective()
    if not affective:
        return {
            "available": False,
            "message": "no FaceEmotion/VoiceEmotion/HumanEmotionState received yet",
            "people": {},
        }
    return {"available": True, "people": affective}


def perception_human_state_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = _bridge(app)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    states = bridge.get_perception_human_state()
    if not states:
        return {
            "available": False,
            "message": "no HumanState received yet on /bonbon/human/state, "
            "or nobody is currently in the scene",
            "people": [],
        }
    return {"available": True, "people": list(states.values())}


def perception_efficiency_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = _bridge(app)
    if bridge is None:
        return {"available": False, "message": "ROS2 bridge not initialised"}
    metrics = bridge.get_perception_efficiency()
    if metrics is None:
        return {
            "available": False,
            "message": "no PerceptionEfficiencyMetrics received yet on "
            "/bonbon/perception_efficiency/metrics",
        }
    return {"available": True, **metrics}


# channel name -> snapshot builder, merged into status_broadcasters.CHANNEL_SNAPSHOTS
PERCEPTION_CHANNEL_SNAPSHOTS = {
    "perception-objects": perception_objects_snapshot,
    "perception-people": perception_people_snapshot,
    "perception-gestures": perception_gestures_snapshot,
    "perception-affective": perception_affective_snapshot,
    "perception-human-state": perception_human_state_snapshot,
    "perception-efficiency": perception_efficiency_snapshot,
}
