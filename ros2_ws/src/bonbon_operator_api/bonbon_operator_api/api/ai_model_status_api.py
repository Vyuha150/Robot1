"""AI model registry / speech / Sarvam / LLM / perception / affective /
gesture status endpoints (Phase 11 of the AI model upgrade brief). Every
handler reads real, current state via bonbon_ai_model_registry (and
bonbon_sarvam_adapter for the Sarvam-specific endpoint) -- nothing here
is a static/hardcoded response. Read endpoints are open to any
authenticated staff user (`diagnostics:read`, matching every other
diagnostics-tier endpoint in this dashboard); the one write endpoint
(POST /ai-models/download/{model_id}) requires the stricter
`config:write` permission and NEVER actually executes a download itself
-- it returns the same license-checked plan
ModelDownloader.download_plan()/print_download_plan() would produce, with
`dryRun` always true over the API (a real download is a deliberate,
human-run CLI action per docs/AI_MODEL_DOWNLOAD_AND_LICENSE_PLAN.md, not
something a dashboard button silently triggers).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.websocket.ai_model_snapshots import (
    build_ai_model_publisher,
    affective_ai_snapshot,
    ai_models_snapshot,
    perception_ai_snapshot,
    sarvam_snapshot,
    speech_ai_snapshot,
)

logger = logging.getLogger(__name__)

ai_model_status_router = APIRouter(tags=["ai-models"])


def _unavailable_response(snapshot: dict) -> APIResponse:
    return APIResponse.ok(snapshot) if snapshot.get("available") else APIResponse.fail(snapshot.get("message", "unavailable"))


@ai_model_status_router.get("/ai-models/registry", response_model=APIResponse)
async def get_ai_model_registry(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(ai_models_snapshot(None))


@ai_model_status_router.get("/ai-models/status", response_model=APIResponse)
async def get_ai_model_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(ai_models_snapshot(None))


@ai_model_status_router.get("/ai-models/download-plan", response_model=APIResponse)
async def get_ai_model_download_plan(
    capability: str | None = None,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return APIResponse.fail(str(exc))
    return APIResponse.ok(publisher.download_plan_view(capability))


@ai_model_status_router.post("/ai-models/download/{model_id}", response_model=APIResponse)
async def request_ai_model_download(
    model_id: str,
    current_user: TokenPayload = Depends(require_permission("config:write:limited")),
) -> APIResponse:
    """Never executes a real download from the API -- always dry_run.
    Real downloads are a deliberate CLI action (scripts/ai_models/*.sh,
    scripts/ai_models/benchmark_all_models.py) run by a human with shell
    access, not a dashboard button, per rule 2's "check license and
    storage before download" needing a human in the loop for anything
    not already enabled_by_default in the registry.

    Permission is "config:write:limited" (engineer+), not the plain
    "config:write" string -- role_permissions.py only ever grants the
    ":limited"/":critical" suffixed forms, never the bare string, so
    requiring the bare form would make this endpoint unreachable by any
    role. ":limited" (not ":critical"/admin-only) matches this endpoint's
    actual risk level: it can never execute a real download (always
    dry_run=True above), so it belongs at the same tier as other
    engineer-level diagnostics actions, not admin-only."""
    try:
        from bonbon_ai_model_registry.model_downloader import ModelDownloader
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        from bonbon_operator_api.websocket.ai_model_snapshots import REGISTRY_PATH

        registry = ModelRegistry.load(REGISTRY_PATH)
    except (ImportError, FileNotFoundError) as exc:
        return APIResponse.fail(str(exc))

    downloader = ModelDownloader(LicenseChecker(), registry)
    result = downloader.download(model_id, dry_run=True)
    if result is None or registry.get(model_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown model_id {model_id!r}")

    logger.info("AI model download plan requested by %s for model_id=%s: %s", current_user.username, model_id, result.message)
    return APIResponse.ok({"modelId": result.model_id, "attempted": result.attempted, "wouldSucceed": result.succeeded, "message": result.message, "dryRun": True})


@ai_model_status_router.get("/ai-models/benchmark", response_model=APIResponse)
async def get_ai_model_benchmark(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    """Returns the last benchmark run's results if
    scripts/ai_models/benchmark_all_models.py has been run and its
    output persisted (see docs/AI_MODEL_BENCHMARK_REPORT.md) -- this
    endpoint does not itself run a fresh benchmark (an LLM/ASR/TTS
    benchmark is a multi-second-to-minutes operation, not something an
    HTTP GET should trigger synchronously)."""
    import json
    from pathlib import Path

    results_path = Path(__file__).resolve().parents[5] / "docs" / "project-status" / "ai_model_benchmark_results.json"
    if not results_path.is_file():
        return APIResponse.ok({"available": False, "message": "No benchmark has been run yet -- run scripts/ai_models/benchmark_all_models.py"})
    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return APIResponse.fail(f"failed to read benchmark results: {exc}")
    return APIResponse.ok({"available": True, **data})


@ai_model_status_router.get("/speech-ai/status", response_model=APIResponse)
async def get_speech_ai_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(speech_ai_snapshot(None))


@ai_model_status_router.get("/speech-ai/asr", response_model=APIResponse)
async def get_speech_ai_asr(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return APIResponse.fail(str(exc))
    return APIResponse.ok(publisher.status_for_capabilities(["asr", "vad", "wake_word"]))


@ai_model_status_router.get("/speech-ai/tts", response_model=APIResponse)
async def get_speech_ai_tts(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return APIResponse.fail(str(exc))
    return APIResponse.ok(publisher.status_for_capabilities(["tts"]))


@ai_model_status_router.get("/sarvam/status", response_model=APIResponse)
async def get_sarvam_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(sarvam_snapshot(None))


@ai_model_status_router.get("/llm-local/status", response_model=APIResponse)
async def get_llm_local_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return APIResponse.fail(str(exc))
    return APIResponse.ok(publisher.status_for_capabilities(["local_llm", "local_rag", "hospital_faq"]))


@ai_model_status_router.get("/perception-ai/status", response_model=APIResponse)
async def get_perception_ai_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(perception_ai_snapshot(None))


@ai_model_status_router.get("/affective-ai/status", response_model=APIResponse)
async def get_affective_ai_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    return _unavailable_response(affective_ai_snapshot(None))


@ai_model_status_router.get("/gesture-ai/status", response_model=APIResponse)
async def get_gesture_ai_status(current_user: TokenPayload = Depends(require_permission("diagnostics:read"))) -> APIResponse:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return APIResponse.fail(str(exc))
    return APIResponse.ok(publisher.status_for_capabilities(["gesture_recognition", "pose_estimation"]))
