"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.accelerator_manager.
Covers the VisionRuntimeInterface output envelope's required fields
(timestamp, frame_id, runtime_source, model_id, confidence, latency_ms,
stale_result) and mock-mode selection (no real Hailo/OAK-D hardware
needed -- forcing RuntimeMode.MOCK keeps this test hardware-independent)."""

from __future__ import annotations

import unittest


class TestAcceleratorManagerCapabilityGuard(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.accelerator_manager import AcceleratorManager

        self.manager = AcceleratorManager()

    def test_non_vision_capability_is_rejected(self):
        from bonbon_ai_runtime.runtime_selector import RuntimeMode, RuntimeSpec

        with self.assertRaises(ValueError):
            self.manager.select("local_llm", RuntimeSpec(mode=RuntimeMode.MOCK))

    def test_mock_mode_selection_for_object_detection_succeeds(self):
        from bonbon_ai_runtime.runtime_selector import RuntimeMode, RuntimeSpec

        result = self.manager.select("object_detection", RuntimeSpec(mode=RuntimeMode.MOCK))
        self.assertEqual(result.selected_kind.value, "mock")


class TestVisionOutputEnvelope(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.accelerator_manager import AcceleratorManager

        self.manager = AcceleratorManager(stale_after_sec=0.5)

    def test_output_envelope_has_all_required_fields(self):
        envelope = self.manager.wrap_output(
            "object_detection", "yolo_hailo", "frame-42", confidence=0.87, latency_ms=12.5
        )
        as_dict = envelope.to_dict()
        for field in ("timestamp", "frameId", "runtimeSource", "modelId", "confidence", "latencyMs", "staleResult"):
            self.assertIn(field, as_dict)

    def test_fresh_output_is_not_stale(self):
        import time

        envelope = self.manager.wrap_output(
            "object_detection", "yolo_hailo", "frame-1", confidence=0.9, latency_ms=10.0, produced_at=time.monotonic()
        )
        self.assertFalse(envelope.stale_result)

    def test_old_output_past_stale_threshold_is_marked_stale(self):
        import time

        old_time = time.monotonic() - 5.0  # well past the 0.5s stale_after_sec
        envelope = self.manager.wrap_output(
            "object_detection", "yolo_hailo", "frame-1", confidence=0.9, latency_ms=10.0, produced_at=old_time
        )
        self.assertTrue(envelope.stale_result)

    def test_status_is_empty_until_select_is_called_for_a_capability(self):
        # Never fabricated as "unavailable" -- genuinely absent until select() runs.
        self.assertEqual(self.manager.status(), {})

    def test_status_reports_last_selection_per_capability_after_select(self):
        from bonbon_ai_runtime.runtime_selector import RuntimeMode, RuntimeSpec

        self.manager.select("gesture_recognition", RuntimeSpec(mode=RuntimeMode.MOCK))
        status = self.manager.status()
        self.assertIn("gesture_recognition", status)
        self.assertIn("selectedAtMonotonic", status["gesture_recognition"])


if __name__ == "__main__":
    unittest.main()
