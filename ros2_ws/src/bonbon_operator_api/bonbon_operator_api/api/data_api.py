"""Data/training/fine-tuning pipeline dashboard API (Phase 8).

Every endpoint reads REAL data from the same underlying stores
validation_api.py already uses for /field-learning, /datasets, and
/models -- this is a rollup under the /data/* path names the brief
requests, not a second data path. New state lives only where genuinely
new: config/data/dataset_registry.yaml (source training datasets, not
deployed model artifacts), config/data/training_targets.yaml, and
bonbon_data_pipeline.export_for_edge's EdgeDeploymentTracker.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

data_router = APIRouter(tags=["data-pipeline"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DATASET_REGISTRY_PATH = _REPO_ROOT / "config" / "data" / "dataset_registry.yaml"
_TRAINING_TARGETS_PATH = _REPO_ROOT / "config" / "data" / "training_targets.yaml"
_MODEL_EXPORT_TARGETS_PATH = _REPO_ROOT / "config" / "data" / "model_export_targets.yaml"


def _status_dir(request: Request) -> Path:
    return request.app.state.cfg.project_status_dir


def _field_learning_dir(request: Request) -> Path:
    d = _status_dir(request) / "project-status" / "field_learning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _edge_deployment_path(request: Request) -> Path:
    return _status_dir(request) / "project-status" / "field_learning" / "edge_deployments.json"


# ── GET /data/datasets ───────────────────────────────────────────────────


@data_router.get("/data/datasets", response_model=APIResponse)
async def data_datasets(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Every registered source training dataset -- config/data/dataset_registry.yaml."""
    try:
        from bonbon_data_pipeline.dataset_registry import DatasetRegistry
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_data_pipeline not importable: {exc}"})

    if not _DATASET_REGISTRY_PATH.is_file():
        return APIResponse.ok({"available": False, "message": "dataset_registry.yaml not found"})

    registry = DatasetRegistry.load(_DATASET_REGISTRY_PATH)
    entries = registry.all()
    by_status = {
        "APPROVED": sum(1 for e in entries if e.status == "APPROVED"),
        "NEEDS_REVIEW": sum(1 for e in entries if e.status == "NEEDS_REVIEW"),
        "BLOCKED": sum(1 for e in entries if e.status == "BLOCKED"),
    }
    return APIResponse.ok(
        {
            "available": True,
            "count": len(entries),
            "countByStatus": by_status,
            "datasets": [e.to_dict() for e in entries],
        }
    )


# ── GET /data/license-status ─────────────────────────────────────────────


@data_router.get("/data/license-status", response_model=APIResponse)
async def data_license_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Live DatasetLicenseChecker decision for every registered dataset --
    never just the static `status` field, always the real gate result."""
    try:
        from bonbon_data_pipeline.dataset_license_checker import DatasetLicenseChecker
        from bonbon_data_pipeline.dataset_registry import DatasetRegistry
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_data_pipeline not importable: {exc}"})

    if not _DATASET_REGISTRY_PATH.is_file():
        return APIResponse.ok({"available": False, "message": "dataset_registry.yaml not found"})

    registry = DatasetRegistry.load(_DATASET_REGISTRY_PATH)
    checker = DatasetLicenseChecker()
    decisions = [
        {
            "datasetId": d.dataset_id,
            "allowedForResearch": checker.check(d).allowed,
            "allowedForProductionTraining": checker.check(d, production_training=True).allowed,
            "reason": checker.check(d).reason,
        }
        for d in registry.all()
    ]
    return APIResponse.ok({"available": True, "count": len(decisions), "licenseStatus": decisions})


# ── GET /data/failure-cases ───────────────────────────────────────────────


@data_router.get("/data/failure-cases", response_model=APIResponse)
async def data_failure_cases(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Same AnonymizedEventStore validation_api.py's /field-learning/failure-cases
    reads -- exposed under the /data/* path the brief names, not a second store."""
    try:
        from bonbon_field_learning import AnonymizedEventStore, HumanReviewQueue
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_field_learning not importable: {exc}"})

    field_dir = _field_learning_dir(request)
    store = AnonymizedEventStore(field_dir / "events.jsonl")
    queue = HumanReviewQueue(field_dir / "review_queue.jsonl")
    events = store.all_events()
    approved = queue.approved()

    return APIResponse.ok(
        {
            "available": True,
            "count": len(events),
            "openCount": len(queue.pending()),
            # "approved" means a human confirmed the correction -- it does NOT by
            # itself mean a regression scenario was generated (that's a separate,
            # explicit RegressionTestGenerator.generate() call; see
            # /data/regression-tests for what was actually converted).
            "approvedCount": len(approved),
            "failureRateByFamily": store.failure_rate_by_family(),
            "events": [e.to_dict() for e in events[-100:]],
        }
    )


# ── POST /data/failure-cases/review ────────────────────────────────────────


class FailureCaseReviewRequest(BaseModel):
    event_id: str
    approve: bool
    corrected_expected_outcome: dict[str, str] = {}
    notes: str = ""


@data_router.post("/data/failure-cases/review", response_model=APIResponse)
async def data_failure_cases_review(
    request: Request,
    body: FailureCaseReviewRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:write")),
) -> APIResponse:
    """Submits a human review decision -- reuses bonbon_field_learning.HumanReviewQueue,
    the same queue RegressionTestGenerator reads an APPROVED item from."""
    try:
        from bonbon_field_learning import AnonymizedEventStore, HumanReviewQueue
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"bonbon_field_learning not importable: {exc}") from exc

    field_dir = _field_learning_dir(request)
    store = AnonymizedEventStore(field_dir / "events.jsonl")
    known_ids = {e.event_id for e in store.all_events()}
    if body.event_id not in known_ids:
        raise HTTPException(status_code=404, detail=f"unknown event_id {body.event_id!r}")

    queue = HumanReviewQueue(field_dir / "review_queue.jsonl")
    item = queue.submit_review(
        event_id=body.event_id,
        reviewer=current_user.sub,
        approve=body.approve,
        corrected_expected_outcome=body.corrected_expected_outcome,
        notes=body.notes,
    )
    return APIResponse.ok({"reviewed": True, "item": item.to_dict()})


# ── GET /data/training-runs ──────────────────────────────────────────────


@data_router.get("/data/training-runs", response_model=APIResponse)
async def data_training_runs(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Per-capability training targets (config/data/training_targets.yaml)
    plus a live cross-check against the dataset registry -- whether the
    declared datasets are actually usable for training right now."""
    try:
        from bonbon_data_pipeline.dataset_registry import DatasetRegistry
        from bonbon_data_pipeline.training_manifest import TrainingManifest
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_data_pipeline not importable: {exc}"})

    if not _TRAINING_TARGETS_PATH.is_file() or not _DATASET_REGISTRY_PATH.is_file():
        return APIResponse.ok({"available": False, "message": "training_targets.yaml or dataset_registry.yaml not found"})

    manifest = TrainingManifest.load(_TRAINING_TARGETS_PATH)
    registry = DatasetRegistry.load(_DATASET_REGISTRY_PATH)
    problems = manifest.validate_against_registry(registry)

    return APIResponse.ok(
        {
            "available": True,
            "count": len(manifest.all()),
            "targets": [t.to_dict() for t in manifest.all()],
            "readyForProductionTraining": len(problems) == 0,
            "blockingIssues": problems,
        }
    )


# ── GET /data/model-evaluations ──────────────────────────────────────────


@data_router.get("/data/model-evaluations", response_model=APIResponse)
async def data_model_evaluations(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Same ModelEvaluationTracker history validation_api.py's /models/evaluation
    reads, exposed under /data/* for this brief's dashboard section."""
    try:
        from bonbon_field_learning import ModelEvaluationTracker
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_field_learning not importable: {exc}"})

    tracker = ModelEvaluationTracker(_field_learning_dir(request) / "model_evaluation.json")
    history = tracker.history()
    latest = tracker.latest()
    return APIResponse.ok(
        {
            "available": True,
            "latest": latest.to_dict() if latest else None,
            "history": [h.to_dict() for h in history],
        }
    )


# ── GET /data/regression-tests ───────────────────────────────────────────


@data_router.get("/data/regression-tests", response_model=APIResponse)
async def data_regression_tests(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Same regression scenario catalog validation_api.py's
    /field-learning/regression-tests reads."""
    try:
        from bonbon_field_learning import RegressionTestGenerator
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_field_learning not importable: {exc}"})

    scenarios = RegressionTestGenerator().all_regression_scenarios()
    return APIResponse.ok(
        {
            "available": True,
            "count": len(scenarios),
            "scenarios": [
                {"scenarioId": s.scenario_id, "category": s.category, "riskLevel": s.risk_level.value}
                for s in scenarios
            ],
        }
    )


# ── GET /data/edge-models ─────────────────────────────────────────────────


@data_router.get("/data/edge-models", response_model=APIResponse)
async def data_edge_models(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Real edge deployment state (active/fallback/version/rollback per
    capability) from EdgeDeploymentTracker, plus the required export
    format per capability from model_export_targets.yaml."""
    try:
        from bonbon_data_pipeline.export_for_edge import EdgeDeploymentTracker, ExportTargetRegistry
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_data_pipeline not importable: {exc}"})

    export_targets: dict[str, Any] = {}
    if _MODEL_EXPORT_TARGETS_PATH.is_file():
        export_targets = {t.capability: t.to_dict() for t in ExportTargetRegistry.load(_MODEL_EXPORT_TARGETS_PATH).all()}

    tracker = EdgeDeploymentTracker(_edge_deployment_path(request))
    deployments = tracker.all()

    return APIResponse.ok(
        {
            "available": True,
            "count": len(deployments),
            "deployments": [d.to_dict() for d in deployments],
            "exportTargets": export_targets,
        }
    )
