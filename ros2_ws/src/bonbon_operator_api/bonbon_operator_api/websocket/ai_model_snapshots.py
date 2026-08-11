"""Snapshot builders for the 5 new AI-model-stack WebSocket channels
(ai-models, speech-ai, sarvam, perception-ai, affective-ai), following
the exact pattern status_broadcasters.py already established: each
function reads real state fresh on every call (never cached/fabricated)
and returns `{"available": False, "message": ...}` honestly when the
underlying package/config isn't importable/found -- same posture as
ai_runtime_snapshot's own ImportError handling.

Also used directly by api/ai_model_status_api.py's REST endpoints, so
the WebSocket push and REST pull paths can never disagree (same
principle used for bonbon_customer_ui's connection-status dashboard
earlier in this project).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

_REPO_ROOT = Path(__file__).resolve().parents[5]
for _extra in (
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_model_registry",
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_sarvam_adapter",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"


def build_ai_model_publisher():
    """Constructs the registry/selector/health/downloader/publisher stack
    fresh -- cheap (one small YAML parse), matches ai_runtime_snapshot's
    own re-read-every-call pattern rather than a stale cached singleton."""
    from bonbon_ai_model_registry.model_benchmark_runner import BenchmarkReport
    from bonbon_ai_model_registry.model_dashboard_publisher import ModelDashboardPublisher
    from bonbon_ai_model_registry.model_downloader import ModelDownloader
    from bonbon_ai_model_registry.model_health_monitor import ModelHealthMonitor
    from bonbon_ai_model_registry.model_license_checker import LicenseChecker
    from bonbon_ai_model_registry.model_registry import ModelRegistry
    from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector
    from bonbon_sarvam_adapter.sarvam_fallback_policy import bespoke_availability_checker

    registry = ModelRegistry.load(REGISTRY_PATH)
    selector = ModelRuntimeSelector(
        registry,
        bespoke_checkers={
            "asr_sarvam_edge": bespoke_availability_checker("asr"),
            "tts_sarvam_edge": bespoke_availability_checker("tts"),
            "translation_sarvam": bespoke_availability_checker("translation"),
        },
    )
    health = ModelHealthMonitor(registry, selector)
    downloader = ModelDownloader(LicenseChecker(), registry)
    publisher = ModelDashboardPublisher(registry, selector, health, downloader)
    return publisher, BenchmarkReport()


def ai_models_snapshot(_app: FastAPI) -> dict[str, Any]:
    try:
        publisher, _ = build_ai_model_publisher()
    except ImportError as exc:
        return {"available": False, "message": f"bonbon_ai_model_registry not importable: {exc}"}
    except FileNotFoundError as exc:
        return {"available": False, "message": str(exc)}
    return {
        "available": True,
        "registry": publisher.registry_view(),
        "status": publisher.status_view(),
        "readiness": publisher.production_readiness_view(),
    }


def speech_ai_snapshot(_app: FastAPI) -> dict[str, Any]:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, **publisher.status_for_capabilities(["asr", "tts", "vad", "wake_word", "translation"])}


def sarvam_snapshot(_app: FastAPI) -> dict[str, Any]:
    try:
        from bonbon_sarvam_adapter.sarvam_capability_detector import detect_sarvam_capabilities
    except ImportError as exc:
        return {"available": False, "message": f"bonbon_sarvam_adapter not importable: {exc}"}
    caps = detect_sarvam_capabilities()
    return {"available": True, **caps.to_dict()}


def perception_ai_snapshot(_app: FastAPI) -> dict[str, Any]:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return {"available": False, "message": str(exc)}
    return {
        "available": True,
        **publisher.status_for_capabilities(["object_detection", "person_detection", "gesture_recognition", "pose_estimation", "face_recognition"]),
    }


def affective_ai_snapshot(_app: FastAPI) -> dict[str, Any]:
    try:
        publisher, _ = build_ai_model_publisher()
    except (ImportError, FileNotFoundError) as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, **publisher.status_for_capabilities(["face_emotion", "voice_emotion", "speaker_diarization"])}


# channel name -> snapshot builder, merged into status_broadcasters.CHANNEL_SNAPSHOTS
AI_MODEL_CHANNEL_SNAPSHOTS = {
    "ai-models": ai_models_snapshot,
    "speech-ai": speech_ai_snapshot,
    "sarvam": sarvam_snapshot,
    "perception-ai": perception_ai_snapshot,
    "affective-ai": affective_ai_snapshot,
}
