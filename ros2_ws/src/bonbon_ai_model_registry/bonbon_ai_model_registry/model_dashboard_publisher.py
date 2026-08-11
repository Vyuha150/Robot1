"""ModelDashboardPublisher — the one place that turns registry + runtime
selector + health monitor + benchmark results into the exact JSON shapes
Phase 11's dashboard endpoints serve. Kept separate from the FastAPI
route handlers themselves (in bonbon_operator_api) so this logic is
testable without spinning up a web server, and reusable by both the REST
endpoints and the WebSocket broadcaster (same payload, two delivery
paths -- same pattern used for bonbon_customer_ui's connection-status
dashboard earlier in this project).
"""

from __future__ import annotations

import time
from typing import Any

from bonbon_ai_model_registry.model_benchmark_runner import BenchmarkReport
from bonbon_ai_model_registry.model_downloader import ModelDownloader
from bonbon_ai_model_registry.model_health_monitor import ModelHealthMonitor
from bonbon_ai_model_registry.model_registry import ModelRegistry
from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector


class ModelDashboardPublisher:
    def __init__(
        self,
        registry: ModelRegistry,
        selector: ModelRuntimeSelector,
        health_monitor: ModelHealthMonitor,
        downloader: ModelDownloader,
    ) -> None:
        self._registry = registry
        self._selector = selector
        self._health = health_monitor
        self._downloader = downloader

    def registry_view(self) -> dict[str, Any]:
        """GET /ai-models/registry"""
        return {
            "generatedAt": time.time(),
            "models": [e.to_dict() for e in self._registry.all()],
            "validationProblems": self._registry.validate(),
        }

    def status_view(self) -> dict[str, Any]:
        """GET /ai-models/status -- real active/fallback/license/runtime
        per capability, never a static list. Also backs /speech-ai/status,
        /llm-local/status, /perception-ai/status, /affective-ai/status,
        /gesture-ai/status by filtering to the relevant capabilities."""
        statuses = self._selector.select_all()
        out = {}
        for capability, status in statuses.items():
            entry = self._registry.get(status.decision.active_model_id) if status.decision.active_model_id else None
            out[capability] = {
                "requestedModelId": status.decision.requested_model_id,
                "activeModelId": status.decision.active_model_id,
                "activeModelName": entry.model_name if entry else None,
                "license": entry.license if entry else None,
                "commercialAllowed": entry.commercial_allowed if entry else None,
                "runtime": entry.runtime if entry else None,
                "hardwareTarget": entry.hardware_target if entry else None,
                "fallbackActive": status.decision.fallback_active,
                "degraded": status.decision.degraded,
                "reason": status.decision.reason,
                "chainTried": status.decision.chain_tried,
                "checkedAt": status.checked_at,
            }
        return out

    def status_for_capabilities(self, capabilities: list[str]) -> dict[str, Any]:
        full = self.status_view()
        return {c: full[c] for c in capabilities if c in full}

    def download_plan_view(self, capability: str | None = None) -> dict[str, Any]:
        """GET /ai-models/download-plan"""
        return {"generatedAt": time.time(), "plan": self._downloader.download_plan(capability)}

    def benchmark_view(self, report: BenchmarkReport) -> dict[str, Any]:
        """GET /ai-models/benchmark"""
        return {
            "generatedAt": time.time(),
            "summary": report.summary(),
            "results": [
                {
                    "caseId": r.case_id, "modelId": r.model_id, "status": r.status,
                    "latencyMs": r.latency_ms, "detail": r.detail, "fallbackTriggered": r.fallback_triggered,
                }
                for r in report.results
            ],
        }

    def health_view(self) -> dict[str, Any]:
        snapshot = self._health.snapshot()
        return {
            "generatedAt": time.time(),
            "capabilities": {
                cap: [
                    {
                        "modelId": h.model_id, "installed": h.installed, "active": h.active,
                        "fallbackActive": h.fallback_active, "lastLatencyMs": h.last_latency_ms,
                        "lastError": h.last_error,
                    }
                    for h in items
                ]
                for cap, items in snapshot.items()
            },
        }

    def production_readiness_view(self) -> dict[str, Any]:
        """GET /ai-models/status's 'Production Readiness' section (Phase
        11 item 6): download-complete / benchmark pass-fail / hardware
        blocked / license blocked / a transparent deployment score --
        same "never a magic number" principle as
        bonbon_customer_ui's connection-readiness endpoint."""
        statuses = self._selector.select_all()
        total = len(statuses)
        active = sum(1 for s in statuses.values() if s.decision.active_model_id is not None)
        hardware_blocked = [
            cap for cap, s in statuses.items()
            if s.decision.active_model_id is None
            and any(self._registry.get(mid) and self._registry.get(mid).hardware_target in ("hailo_8", "hailo_10h") for mid in s.decision.chain_tried)
        ]
        license_blocked = [
            e.model_id for e in self._registry.all()
            if e.commercial_allowed in ("false", "unknown") and not e.enabled_by_default
        ]
        score = round(100 * active / total) if total else 0
        return {
            "generatedAt": time.time(),
            "capabilitiesTotal": total,
            "capabilitiesActive": active,
            "hardwareBlockedCapabilities": hardware_blocked,
            "licenseBlockedModels": license_blocked,
            "deploymentScore": score,
            "verdict": "PASS" if score >= 90 else "PARTIAL" if score >= 40 else "BLOCKED",
        }
