"""Edge AI Runtime brief Phase 12 dashboard endpoints.

8 genuinely new `/edge-ai/*` endpoints plus `/vision-ai/status` (9 of
the brief's 13 required REST endpoints -- the other 4,
`/ai-models/status`, `/speech-ai/status`, `/llm-local/status`,
`/affective-ai/status`, already exist from the earlier AI-model-stack
pass in api/ai_model_status_api.py and are not duplicated here).

Stateful endpoints (status/model-registry/routes/resource-guard/
degraded-mode/safety-separation/cache) relay the real, live state
edge_ai_runtime_node published from Pi-2 via
websocket/edge_ai_snapshots.py -- so the WebSocket push and REST pull
paths can never disagree, same principle used throughout this
dashboard. /vision-ai/status and /edge-ai/benchmarks follow the older,
config-based ai_model_status_api.py pattern (fresh construction /
results-file read) since that data genuinely is cheaply/honestly
recomputable without needing Pi-2's live process.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.websocket.edge_ai_snapshots import (
    edge_ai_cache_snapshot,
    edge_ai_models_snapshot,
    edge_ai_resources_snapshot,
    edge_ai_routes_snapshot,
    edge_ai_safety_snapshot,
    edge_ai_status_snapshot,
)

logger = logging.getLogger(__name__)

edge_ai_status_router = APIRouter(tags=["edge-ai"])


def _unavailable_response(snapshot: dict) -> APIResponse:
    return APIResponse.ok(snapshot) if snapshot.get("available") else APIResponse.error(snapshot.get("message", "unavailable"))


@edge_ai_status_router.get("/edge-ai/status", response_model=APIResponse)
async def get_edge_ai_status(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(edge_ai_status_snapshot(request.app))


@edge_ai_status_router.get("/edge-ai/model-registry", response_model=APIResponse)
async def get_edge_ai_model_registry(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(edge_ai_models_snapshot(request.app))


@edge_ai_status_router.get("/edge-ai/routes", response_model=APIResponse)
async def get_edge_ai_routes(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(edge_ai_routes_snapshot(request.app))


@edge_ai_status_router.get("/edge-ai/cache", response_model=APIResponse)
async def get_edge_ai_cache(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(edge_ai_cache_snapshot(request.app))


@edge_ai_status_router.get("/edge-ai/resource-guard", response_model=APIResponse)
async def get_edge_ai_resource_guard(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(edge_ai_resources_snapshot(request.app))


@edge_ai_status_router.get("/edge-ai/degraded-mode", response_model=APIResponse)
async def get_edge_ai_degraded_mode(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    status_snapshot = edge_ai_status_snapshot(request.app)
    if not status_snapshot.get("available"):
        return _unavailable_response(status_snapshot)
    return APIResponse.ok(status_snapshot.get("degradedMode", {}))


@edge_ai_status_router.get("/edge-ai/safety-separation", response_model=APIResponse)
async def get_edge_ai_safety_separation(request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(edge_ai_safety_snapshot(request.app))


@edge_ai_status_router.get("/edge-ai/benchmarks", response_model=APIResponse)
async def get_edge_ai_benchmarks(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    """Returns the last edge-AI benchmark run's results if
    scripts/edge_ai/benchmark_edge_ai_stack.py has been run and its
    output persisted (Phase 14) -- like /ai-models/benchmark, this does
    not itself run a fresh benchmark synchronously."""
    results_path = Path(__file__).resolve().parents[5] / "docs" / "project-status" / "edge_ai_benchmark_results.json"
    if not results_path.is_file():
        return APIResponse.ok({"available": False, "message": "No edge AI benchmark has been run yet -- run scripts/edge_ai/benchmark_edge_ai_stack.py"})
    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return APIResponse.error(f"failed to read edge AI benchmark results: {exc}")
    return APIResponse.ok({"available": True, **data})


@edge_ai_status_router.get("/vision-ai/status", response_model=APIResponse)
async def get_vision_ai_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    """Vision-capability model status + accelerator runtime selection.
    Distinct from the existing /perception-ai/status (same underlying
    model registry, but this view also surfaces
    AcceleratorManager.status() -- empty/honest until a real vision
    capability's select() has actually been called on this process)."""
    try:
        from bonbon_edge_ai_runtime.dashboard_publisher import EdgeAIDashboardPublisher
    except ImportError as exc:
        return APIResponse.error(f"bonbon_edge_ai_runtime not importable: {exc}")
    try:
        publisher = EdgeAIDashboardPublisher()
    except FileNotFoundError as exc:
        return APIResponse.error(str(exc))
    return APIResponse.ok(publisher.vision_view())
