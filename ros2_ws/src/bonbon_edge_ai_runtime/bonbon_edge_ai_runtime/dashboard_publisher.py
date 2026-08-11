"""bonbon_edge_ai_runtime.dashboard_publisher -- Edge AI Runtime brief
Phase 2/12. Produces the JSON views for all 9 dashboard cards Phase 12
names.

For the cards that overlap with the existing AI model dashboard (Model
Registry, Speech AI, LLM, Affective AI, and the model-selection half of
Vision AI), this delegates wholesale to
bonbon_ai_model_registry.model_dashboard_publisher.ModelDashboardPublisher
constructed against the MERGED registry (16 original + 3 edge-ai
capabilities, see model_registry.load_merged()) -- not reimplemented.
The 3 new capabilities this package adds (human_state_fusion,
intent_classification, assistant_guardrails) automatically get the same
status/fallback/dashboard-visibility treatment as the original 16
through this delegation, with zero new view code required. This module
adds only the views that don't exist anywhere yet: Edge AI Overview,
Safety Separation, and Resource Guard/Cache.
"""

from __future__ import annotations

import time
from typing import Any


class EdgeAIDashboardPublisher:
    def __init__(
        self,
        *,
        registry=None,
        selector=None,
        accelerator_manager=None,
        cache_manager=None,
        resource_guard=None,
        safety_guard=None,
        scheduler=None,
        config=None,
    ) -> None:
        from bonbon_ai_model_registry.model_dashboard_publisher import ModelDashboardPublisher
        from bonbon_ai_model_registry.model_downloader import ModelDownloader
        from bonbon_ai_model_registry.model_health_monitor import ModelHealthMonitor
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker

        from bonbon_edge_ai_runtime.config_loader import EdgeAIConfig
        from bonbon_edge_ai_runtime.model_registry import load_merged
        from bonbon_edge_ai_runtime.runtime_selector import ModelRuntimeSelector

        self._registry = registry or load_merged()
        self._selector = selector or ModelRuntimeSelector(self._registry)
        self._health = ModelHealthMonitor(self._registry, self._selector)
        self._downloader = ModelDownloader(LicenseChecker(), self._registry)
        self._model_dashboard = ModelDashboardPublisher(
            self._registry, self._selector, self._health, self._downloader
        )

        self._accelerator_manager = accelerator_manager
        self._cache_manager = cache_manager
        self._resource_guard = resource_guard
        self._safety_guard = safety_guard
        self._scheduler = scheduler
        self._config = config or EdgeAIConfig.load()

    # ── Card 1: Edge AI Overview ─────────────────────────────────────

    def overview_view(self, snapshot=None, active_route=None) -> dict[str, Any]:
        """`snapshot` is a metrics_publisher.MetricsSnapshot the caller
        already computed this cycle -- this view composes it rather than
        re-deriving state with fabricated inputs (there is no honest way
        to guess a current temperature or cache hit rate from inside a
        dashboard view alone)."""
        readiness = self._model_dashboard.production_readiness_view()
        return {
            "generatedAt": time.time(),
            "activeRoute": active_route.to_dict() if active_route is not None else None,
            "modelRouterHealth": readiness,
            "cacheHitRate": snapshot.cache_metrics.get("byItemType", {}) if snapshot else {},
            "degradedMode": snapshot.degraded_status if snapshot else {},
            "resourceGuardState": (snapshot.resource_status.get("loadLevel", "unknown") if snapshot else "unknown"),
        }

    # ── Card 2: Model Registry (delegated wholesale) ─────────────────

    def registry_view(self) -> dict[str, Any]:
        return self._model_dashboard.registry_view()

    # ── Card 3: Speech AI (delegated wholesale) ──────────────────────

    def speech_view(self) -> dict[str, Any]:
        return self._model_dashboard.status_for_capabilities(["asr", "tts", "vad", "wake_word", "translation"])

    # ── Card 4: LLM (delegated wholesale) ────────────────────────────

    def llm_view(self) -> dict[str, Any]:
        return self._model_dashboard.status_for_capabilities(["local_llm", "local_rag", "assistant_guardrails"])

    # ── Card 5: Vision AI ─────────────────────────────────────────────

    def vision_view(self) -> dict[str, Any]:
        model_selection = self._model_dashboard.status_for_capabilities(
            ["object_detection", "person_detection", "gesture_recognition", "pose_estimation", "face_recognition"]
        )
        accelerator_status = self._accelerator_manager.status() if self._accelerator_manager else {}
        return {**model_selection, "acceleratorRuntimes": accelerator_status}

    # ── Card 6: Affective AI (delegated wholesale) ───────────────────

    def affective_view(self) -> dict[str, Any]:
        return self._model_dashboard.status_for_capabilities(
            ["face_emotion", "voice_emotion", "speaker_diarization", "human_state_fusion"]
        )

    # ── Card 7: Safety Separation ─────────────────────────────────────

    def safety_separation_view(self) -> dict[str, Any]:
        if self._safety_guard is None:
            return {"available": False, "message": "no SafetySeparationGuard instance provided"}
        summary = self._safety_guard.summary()
        rules = self._config.get("safety_separation")
        return {
            "available": True,
            **summary,
            "actionCategories": rules.get("action_categories", []),
            "authorizedDirectControlSources": rules.get("authorized_direct_control_sources", []),
            "knownGaps": rules.get("known_gaps", []),
        }

    # ── Card 8: Resource Guard ─────────────────────────────────────────

    def resource_guard_view(self, snapshot=None) -> dict[str, Any]:
        if snapshot is None or not snapshot.resource_status:
            return {"available": False, "message": "no resource snapshot computed yet this cycle"}
        return {"available": True, **snapshot.resource_status}

    # ── Card 9: Cache ─────────────────────────────────────────────────

    def cache_view(self) -> dict[str, Any]:
        if self._cache_manager is None:
            return {"available": False, "message": "no CacheManager instance provided"}
        return {"available": True, **self._cache_manager.metrics()}

    # ── Production readiness (includes edge_ai config file presence) ──

    def production_readiness_view(self) -> dict[str, Any]:
        base = self._model_dashboard.production_readiness_view()
        return {
            **base,
            "edgeAiConfigComplete": self._config.all_files_present(),
            "edgeAiConfigMissing": self._config.missing_files(),
        }
