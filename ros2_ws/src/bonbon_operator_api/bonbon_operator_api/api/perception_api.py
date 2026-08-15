"""Dashboard Perception Gap Report Phase 8 -- 11 REST endpoints covering
objects, people, affective state, gestures, human-state, and perception
efficiency. Every one of these categories was previously invisible to an
operator (only a browser-side COCO-SSD demo unrelated to the robot). See
docs/DASHBOARD_PERCEPTION_GAP_REPORT.md.

All endpoints relay the real, live state ros2_bridge.py cached from
/bonbon/vision/objects, /bonbon/persons/tracks, /bonbon/gesture/events,
/bonbon/affective/face_emotion, /bonbon/affective/voice_emotion,
/bonbon/affective/human_state, /bonbon/human/state, and
/bonbon/perception_efficiency/metrics -- so the WebSocket push
(websocket/perception_snapshots.py) and REST pull paths can never disagree,
same principle used throughout this dashboard.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.websocket.perception_snapshots import (
    perception_affective_snapshot,
    perception_efficiency_snapshot,
    perception_gestures_snapshot,
    perception_human_state_snapshot,
    perception_objects_snapshot,
    perception_people_snapshot,
)

logger = logging.getLogger(__name__)

perception_router = APIRouter(tags=["perception"])


def _diag_read(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))):
    return current_user


# ── Objects ──────────────────────────────────────────────────────────────────


@perception_router.get("/perception/objects/status", response_model=APIResponse)
async def get_perception_objects_status(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    snapshot = perception_objects_snapshot(request.app)
    if not snapshot.get("available"):
        return APIResponse.ok(snapshot)
    return APIResponse.ok(
        {
            "available": True,
            "count": len(snapshot["objects"]),
            **snapshot["meta"],
        }
    )


@perception_router.get("/perception/objects/classes", response_model=APIResponse)
async def get_perception_objects_classes(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    snapshot = perception_objects_snapshot(request.app)
    if not snapshot.get("available"):
        return APIResponse.ok(snapshot)
    classes = sorted({obj["class_name"] for obj in snapshot["objects"]})
    return APIResponse.ok({"available": True, "classes": classes})


@perception_router.get("/perception/objects/active", response_model=APIResponse)
async def get_perception_objects_active(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    return APIResponse.ok(perception_objects_snapshot(request.app))


# ── People ───────────────────────────────────────────────────────────────────


@perception_router.get("/perception/people/status", response_model=APIResponse)
async def get_perception_people_status(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    snapshot = perception_people_snapshot(request.app)
    people = snapshot.get("people", [])
    known = sum(1 for p in people if p.get("known_person_id"))
    return APIResponse.ok(
        {
            "available": snapshot.get("available", False),
            "message": snapshot.get("message"),
            "active_count": len(people),
            "known_count": known,
            "unknown_count": len(people) - known,
        }
    )


@perception_router.get("/perception/people/active", response_model=APIResponse)
async def get_perception_people_active(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    return APIResponse.ok(perception_people_snapshot(request.app))


# ── Affective ────────────────────────────────────────────────────────────────


@perception_router.get("/perception/affective/status", response_model=APIResponse)
async def get_perception_affective_status(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    snapshot = perception_affective_snapshot(request.app)
    people = snapshot.get("people", {})
    return APIResponse.ok(
        {
            "available": snapshot.get("available", False),
            "message": snapshot.get("message"),
            "tracked_people": len(people),
        }
    )


@perception_router.get("/perception/affective/human-states", response_model=APIResponse)
async def get_perception_affective_human_states(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    return APIResponse.ok(perception_affective_snapshot(request.app))


# ── Gestures ─────────────────────────────────────────────────────────────────


@perception_router.get("/perception/gestures/status", response_model=APIResponse)
async def get_perception_gestures_status(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    snapshot = perception_gestures_snapshot(request.app)
    gestures = snapshot.get("gestures", [])
    return APIResponse.ok(
        {
            "available": snapshot.get("available", False),
            "message": snapshot.get("message"),
            "recent_count": len(gestures),
            "last_gesture_type": gestures[-1]["gesture_type"] if gestures else None,
        }
    )


@perception_router.get("/perception/gestures/active", response_model=APIResponse)
async def get_perception_gestures_active(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    return APIResponse.ok(perception_gestures_snapshot(request.app))


# ── Human state (bonbon_human_state_fusion) ─────────────────────────────────


@perception_router.get("/perception/human-state/active", response_model=APIResponse)
async def get_perception_human_state_active(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    return APIResponse.ok(perception_human_state_snapshot(request.app))


# ── Efficiency ───────────────────────────────────────────────────────────────


@perception_router.get("/perception/efficiency/status", response_model=APIResponse)
async def get_perception_efficiency_status(
    request: Request, current_user: TokenPayload = Depends(_diag_read)
) -> APIResponse:
    return APIResponse.ok(perception_efficiency_snapshot(request.app))
