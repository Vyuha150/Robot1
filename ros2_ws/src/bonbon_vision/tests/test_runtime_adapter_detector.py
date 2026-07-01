"""Tests for ObjectDetectorRuntimeAdapter -- the fix wiring bonbon_vision's
live detector through bonbon_ai_runtime's RuntimeSelector (Hailo/CPU/
TensorRT/Mock) instead of calling ultralytics directly.
"""

from __future__ import annotations

import unittest

import numpy as np
from bonbon_ai_runtime import (
    HailoDeviceDetector,
    HailoRuntime,
    MockRuntime,
    RuntimeKind,
    RuntimeSelector,
)
from bonbon_vision.config.vision_config import DetectorConfig
from bonbon_vision.detectors.runtime_adapter_detector import ObjectDetectorRuntimeAdapter


def _absent_hailo_detector() -> HailoDeviceDetector:
    return HailoDeviceDetector(runner=lambda c: None, import_probe=lambda m: False)


def _present_hailo_detector() -> HailoDeviceDetector:
    return HailoDeviceDetector(
        runner=lambda c: (0, "Hailo-8L") if c[0] == "hailortcli" else None,
        import_probe=lambda m: True,
    )


class TestRuntimeAdapterMockFallback(unittest.TestCase):
    """No real Hailo/CPU model configured -- must honestly fall back to mock,
    never claim a fake Hailo PASS."""

    def test_falls_back_to_mock_with_no_model_configured(self):
        cfg = DetectorConfig(backend="runtime", runtime_mode="auto")
        det = ObjectDetectorRuntimeAdapter(cfg)
        det.load_model()
        self.assertEqual(det.selected_runtime_kind, "mock")
        self.assertFalse(det.is_real_accelerator)
        self.assertTrue(det.fallback_active)
        self.assertFalse(det.is_degraded)

    def test_mock_backed_detect_returns_empty_not_degraded(self):
        cfg = DetectorConfig(backend="runtime", runtime_mode="mock")
        det = ObjectDetectorRuntimeAdapter(cfg)
        det.load_model()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = det.detect(frame)
        self.assertFalse(result.is_degraded)
        self.assertEqual(result.detections, [])


class TestRuntimeAdapterHailoSelection(unittest.TestCase):
    """Injected real Hailo device -> auto mode must prefer it."""

    def test_prefers_hailo_when_available(self, *, hef_bytes: bytes = b"x"):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            hef = Path(tmp) / "model.hef"
            hef.write_bytes(hef_bytes)

            cfg = DetectorConfig(
                backend="runtime",
                runtime_mode="auto",
                runtime_priority=["hailo", "mock"],
                hailo_hef_path=str(hef),
            )
            det = ObjectDetectorRuntimeAdapter(cfg)
            det._selector_factory = lambda: RuntimeSelector(
                factory=lambda kind: (
                    HailoRuntime(
                        detector=_present_hailo_detector(),
                        infer_factory=lambda p: (lambda t: [np.zeros((0, 6), np.float32)]),
                    )
                    if kind == RuntimeKind.HAILO
                    else MockRuntime()
                )
            )
            det.load_model()
            self.assertEqual(det.selected_runtime_kind, "hailo")
            self.assertTrue(det.is_real_accelerator)
            self.assertFalse(det.fallback_active)

    def test_falls_back_when_hailo_absent(self):
        cfg = DetectorConfig(
            backend="runtime", runtime_mode="auto", runtime_priority=["hailo", "mock"]
        )
        det = ObjectDetectorRuntimeAdapter(cfg)
        det._selector_factory = lambda: RuntimeSelector(
            factory=lambda kind: (
                HailoRuntime(detector=_absent_hailo_detector())
                if kind == RuntimeKind.HAILO
                else MockRuntime()
            )
        )
        det.load_model()
        self.assertNotEqual(det.selected_runtime_kind, "hailo")
        self.assertFalse(det.is_real_accelerator)
        self.assertTrue(det.fallback_active)
        self.assertIn("hailo", det.fallback_reason.lower())


class TestRuntimeAdapterDetectionDecoding(unittest.TestCase):
    """(N, 6) [x1,y1,x2,y2,conf,cls] tensor decoding into ObjectDetection."""

    def test_decodes_detections_above_threshold(self):
        cfg = DetectorConfig(backend="runtime", runtime_mode="mock", confidence_threshold=0.5)
        det = ObjectDetectorRuntimeAdapter(cfg)

        class _FakeMock(MockRuntime):
            def infer(self, input_tensor, timeout_ms: float = 300.0):
                from bonbon_ai_runtime import InferenceOutput

                raw = np.array(
                    [
                        [10, 10, 50, 90, 0.9, 0],  # person, above threshold
                        [5, 5, 20, 20, 0.1, 56],  # chair, below threshold -> dropped
                    ],
                    dtype=np.float32,
                )
                return InferenceOutput(outputs=[raw], latency_ms=1.0)

        det._selector_factory = lambda: RuntimeSelector(factory=lambda kind: _FakeMock())
        det.load_model()

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = det.detect(frame)
        self.assertEqual(len(result.detections), 1)
        self.assertEqual(result.detections[0].class_name, "person")
        self.assertAlmostEqual(result.detections[0].confidence, 0.9, places=3)

    def test_no_selection_returns_empty(self):
        cfg = DetectorConfig(backend="runtime")
        det = ObjectDetectorRuntimeAdapter(cfg)
        # load_model() never called -- _selection stays None.
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = det.detect(frame)
        self.assertEqual(result.detections, [])


if __name__ == "__main__":
    unittest.main()
