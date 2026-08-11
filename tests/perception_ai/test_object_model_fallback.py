"""Tests for the object_detection fallback chain (Hailo -> CPU ONNX ->
Ultralytics direct -> mock) as configured in the registry -- GAP-2's
"registered honestly, dashboard-visible, consolidation deferred" decision,
and the hospital class allowlist (bonbon_perception_ai's Phase 7 addition)
that filters whichever detector's raw output before it reaches fusion."""

from __future__ import annotations

import unittest
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml"


class TestObjectDetectionFallbackChainConfiguration(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_three_real_implementations_are_all_registered(self):
        entries = self.registry.by_capability("object_detection")
        model_ids = {e.model_id for e in entries}
        self.assertEqual(
            model_ids,
            {"vision_hailo_yolo", "vision_cpu_onnx_runtime_adapter", "vision_ultralytics_direct", "vision_mock"},
        )

    def test_chain_from_hailo_cascades_through_cpu_and_ultralytics_to_mock(self):
        chain = [e.model_id for e in self.registry.fallback_chain("vision_hailo_yolo")]
        self.assertEqual(
            chain,
            ["vision_hailo_yolo", "vision_cpu_onnx_runtime_adapter", "vision_ultralytics_direct", "vision_mock"],
        )

    def test_selection_with_only_mock_available_lands_on_mock(self):
        from bonbon_ai_model_registry.model_fallback_policy import FallbackPolicy

        policy = FallbackPolicy(self.registry)
        availability = {
            "vision_hailo_yolo": False,
            "vision_cpu_onnx_runtime_adapter": False,
            "vision_ultralytics_direct": False,
            "vision_mock": True,
        }
        decision = policy.resolve("object_detection", availability, preferred_model_id="vision_hailo_yolo")
        self.assertEqual(decision.active_model_id, "vision_mock")
        self.assertTrue(decision.fallback_active)
        self.assertFalse(decision.degraded)

    def test_selection_with_nothing_available_is_honestly_degraded(self):
        from bonbon_ai_model_registry.model_fallback_policy import FallbackPolicy

        policy = FallbackPolicy(self.registry)
        availability = {mid: False for mid in ("vision_hailo_yolo", "vision_cpu_onnx_runtime_adapter", "vision_ultralytics_direct", "vision_mock")}
        decision = policy.resolve("object_detection", availability, preferred_model_id="vision_hailo_yolo")
        self.assertIsNone(decision.active_model_id)
        self.assertTrue(decision.degraded)


class TestHospitalClassAllowlist(unittest.TestCase):
    """Rule: unsupported classes must not be hallucinated through --
    whichever of the 3 detector implementations is active, its raw output
    must be filtered through this allowlist before reaching fusion."""

    def setUp(self):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_perception_ai"))
        from bonbon_perception_ai.config.hospital_class_registry import filter_detections, is_hospital_specific

        self.filter_detections = filter_detections
        self.is_hospital_specific = is_hospital_specific

    def test_supported_generic_class_passes_through(self):
        detections = [{"class_name": "person", "confidence": 0.9}]
        self.assertEqual(self.filter_detections(detections), detections)

    def test_hallucinated_unsupported_class_is_dropped_not_relabeled(self):
        detections = [{"class_name": "giraffe", "confidence": 0.7}, {"class_name": "person", "confidence": 0.9}]
        filtered = self.filter_detections(detections)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["class_name"], "person")

    def test_hospital_specific_class_is_flagged_correctly(self):
        self.assertTrue(self.is_hospital_specific("wheelchair"))
        self.assertFalse(self.is_hospital_specific("person"))
        self.assertFalse(self.is_hospital_specific("giraffe"))


if __name__ == "__main__":
    unittest.main()
