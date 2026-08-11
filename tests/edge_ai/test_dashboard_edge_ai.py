"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.dashboard_publisher.
Exercises all 9 EdgeAIDashboardPublisher dashboard-card views plus
production_readiness_view. The card views that delegate wholesale to
ModelDashboardPublisher (registry/speech/llm/affective) get their own
deep coverage from tests/ai_models/ and tests/dashboard/ -- these tests
check EdgeAIDashboardPublisher's own wiring: which views require which
optional collaborator, and that a missing collaborator is reported
honestly (available: False), never fabricated."""

from __future__ import annotations

import unittest


class TestDashboardPublisherConstructsWithNoOptionalCollaborators(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.dashboard_publisher import EdgeAIDashboardPublisher

        self.publisher = EdgeAIDashboardPublisher()

    def test_registry_view_delegates_to_model_dashboard(self):
        view = self.publisher.registry_view()
        self.assertIsInstance(view, dict)

    def test_speech_view_returns_a_dict(self):
        self.assertIsInstance(self.publisher.speech_view(), dict)

    def test_llm_view_returns_a_dict(self):
        self.assertIsInstance(self.publisher.llm_view(), dict)

    def test_affective_view_returns_a_dict(self):
        self.assertIsInstance(self.publisher.affective_view(), dict)

    def test_vision_view_has_accelerator_runtimes_key_even_without_manager(self):
        view = self.publisher.vision_view()
        self.assertIn("acceleratorRuntimes", view)
        self.assertEqual(view["acceleratorRuntimes"], {})  # honestly empty, not fabricated

    def test_safety_separation_view_honestly_unavailable_without_guard(self):
        view = self.publisher.safety_separation_view()
        self.assertFalse(view["available"])

    def test_resource_guard_view_honestly_unavailable_without_snapshot(self):
        view = self.publisher.resource_guard_view()
        self.assertFalse(view["available"])

    def test_cache_view_honestly_unavailable_without_cache_manager(self):
        view = self.publisher.cache_view()
        self.assertFalse(view["available"])

    def test_overview_view_has_required_keys(self):
        view = self.publisher.overview_view()
        for field in ("generatedAt", "activeRoute", "modelRouterHealth", "cacheHitRate", "degradedMode", "resourceGuardState"):
            self.assertIn(field, view)
        self.assertEqual(view["resourceGuardState"], "unknown")  # honest default, no snapshot given

    def test_production_readiness_view_reports_edge_ai_config_present(self):
        view = self.publisher.production_readiness_view()
        self.assertTrue(view["edgeAiConfigComplete"], f"missing edge_ai config files: {view['edgeAiConfigMissing']}")
        self.assertEqual(view["edgeAiConfigMissing"], [])


class TestDashboardPublisherWithRealCollaborators(unittest.TestCase):
    def test_safety_separation_view_reports_real_guard_summary_when_provided(self):
        from bonbon_edge_ai_runtime.dashboard_publisher import EdgeAIDashboardPublisher
        from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

        guard = SafetySeparationGuard()
        guard.classify("llm", "direct_motor_command", {})
        publisher = EdgeAIDashboardPublisher(safety_guard=guard)

        view = publisher.safety_separation_view()
        self.assertTrue(view["available"])
        self.assertEqual(view["totalBlocked"], 1)
        self.assertIn("actionCategories", view)

    def test_cache_view_reports_real_metrics_when_provided(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheManager
        from bonbon_edge_ai_runtime.dashboard_publisher import EdgeAIDashboardPublisher

        cache = CacheManager()
        cache.record("tts", hit=True, latency_saved_ms=500.0)
        publisher = EdgeAIDashboardPublisher(cache_manager=cache)

        view = publisher.cache_view()
        self.assertTrue(view["available"])
        self.assertEqual(view["byItemType"]["tts"]["hits"], 1)

    def test_vision_view_reports_real_accelerator_status_when_provided(self):
        from bonbon_ai_runtime.runtime_selector import RuntimeMode, RuntimeSpec
        from bonbon_edge_ai_runtime.accelerator_manager import AcceleratorManager
        from bonbon_edge_ai_runtime.dashboard_publisher import EdgeAIDashboardPublisher

        accel = AcceleratorManager()
        accel.select("object_detection", RuntimeSpec(mode=RuntimeMode.MOCK))
        publisher = EdgeAIDashboardPublisher(accelerator_manager=accel)

        view = publisher.vision_view()
        self.assertIn("object_detection", view["acceleratorRuntimes"])


if __name__ == "__main__":
    unittest.main()
