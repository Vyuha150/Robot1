"""Facility Map Editor — staff-only, export-only for this pass.

Staff drop pins on the scanned occupancy-grid map and export a
`named_locations` YAML block to paste into bonbon_navigation's
nav_params.yaml, then relaunch. This router never calls into
bonbon_navigation to mutate its location registry (see plan decision).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from bonbon_patient_kiosk.auth.dependencies import require_permission
from bonbon_patient_kiosk.models.auth_models import TokenPayload
from bonbon_patient_kiosk.models.facility_models import FacilityMapExport, NamedLocationLabelUpsert
from bonbon_patient_kiosk.models.response_models import APIResponse

facility_map_router = APIRouter(prefix="/facility-map", tags=["facility-map"])


@facility_map_router.get("/labels", response_model=APIResponse)
async def list_labels(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("facility_map:read")),
) -> APIResponse:
    return APIResponse.ok(request.app.state.facility_label_store.list())


@facility_map_router.post("/labels", response_model=APIResponse, status_code=201)
async def create_label(
    request: Request,
    body: NamedLocationLabelUpsert,
    current_user: TokenPayload = Depends(require_permission("facility_map:write")),
) -> APIResponse:
    try:
        label = request.app.state.facility_label_store.upsert(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit_logger.log(
        actor_id=current_user.sub,
        actor_role=current_user.role,
        action="facility_map:label_create",
        target=label.label_id,
        outcome="success",
        request_data={"name": label.name, "category": label.category},
    )
    return APIResponse.ok(label)


@facility_map_router.put("/labels/{label_id}", response_model=APIResponse)
async def update_label(
    request: Request,
    label_id: str,
    body: NamedLocationLabelUpsert,
    current_user: TokenPayload = Depends(require_permission("facility_map:write")),
) -> APIResponse:
    try:
        label = request.app.state.facility_label_store.upsert(body, label_id=label_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit_logger.log(
        actor_id=current_user.sub,
        actor_role=current_user.role,
        action="facility_map:label_update",
        target=label_id,
        outcome="success",
    )
    return APIResponse.ok(label)


@facility_map_router.delete("/labels/{label_id}", response_model=APIResponse)
async def delete_label(
    request: Request,
    label_id: str,
    current_user: TokenPayload = Depends(require_permission("facility_map:write")),
) -> APIResponse:
    deleted = request.app.state.facility_label_store.delete(label_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Label not found")
    request.app.state.audit_logger.log(
        actor_id=current_user.sub,
        actor_role=current_user.role,
        action="facility_map:label_delete",
        target=label_id,
        outcome="success",
    )
    return APIResponse.ok({"deleted": True, "label_id": label_id})


@facility_map_router.get("/export", response_model=APIResponse)
async def export_yaml(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("facility_map:export")),
) -> APIResponse:
    store = request.app.state.facility_label_store
    yaml_text = store.export_yaml()
    request.app.state.audit_logger.log(
        actor_id=current_user.sub,
        actor_role=current_user.role,
        action="facility_map:export",
        outcome="success",
        request_data={"label_count": len(store.list())},
    )
    return APIResponse.ok(FacilityMapExport(yaml_text=yaml_text, label_count=len(store.list())))
