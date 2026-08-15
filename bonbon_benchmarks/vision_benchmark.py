"""Vision/gesture/face perception benchmarking (FPS, latency).

Every metric here needs a real camera frame stream (object detection,
gesture, face recognition all take image data as input) -- this dev
environment has no OpenCV (`cv2`) installed and no camera device, so
every metric is honestly BLOCKED rather than measured against a
synthetic/fabricated frame. What CAN be confirmed here is that the
runtime-selection layer itself (`bonbon_ai_runtime.RuntimeSelector`,
already built and tested) is importable and would correctly select a
CPU/mock runtime when Hailo hardware is absent -- that is reported as
context, not as a substitute for a real FPS number.
"""

from __future__ import annotations

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import BenchmarkCategoryReport, BenchmarkMetric


def _cv2_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def _runtime_selector_note() -> str:
    try:
        from bonbon_ai_runtime import (  # noqa: F401
            RuntimeKind,
            RuntimeMode,
            RuntimeSelector,
            RuntimeSpec,
        )

        return "bonbon_ai_runtime.RuntimeSelector is importable and would resolve hailo->cpu->mock correctly (see docs/HAILO_RUNTIME_STRATEGY.md); no real camera to feed it a frame here."
    except ImportError as exc:
        return f"bonbon_ai_runtime not importable: {exc}"


def _blocked(name: str, module: str, scenario: str, unit: str = "fps") -> BenchmarkMetric:
    return BenchmarkMetric.blocked(
        metric_name=name, board="ai_pi", module=module, scenario=scenario, unit=unit,
        reason="no OpenCV/camera device in this environment" if not _cv2_available() else "no real camera frame stream available",
        recommendation=_runtime_selector_note(),
    )


def benchmark_object_detection_fps() -> BenchmarkMetric:
    return _blocked("object_detection_fps", "vision", "continuous object detection on live camera feed")


def benchmark_person_detection_fps() -> BenchmarkMetric:
    return _blocked("person_detection_fps", "vision", "continuous person detection on live camera feed")


def benchmark_gesture_recognition_fps() -> BenchmarkMetric:
    return _blocked("gesture_recognition_fps", "vision", "landmark-based gesture classification on live feed")


def benchmark_face_recognition_latency() -> BenchmarkMetric:
    return _blocked("face_recognition_latency", "vision", "face embedding + match against enrolled staff", unit="ms")


def benchmark_face_emotion_update_rate() -> BenchmarkMetric:
    return _blocked("face_emotion_update_rate", "vision", "active-person-only face emotion inference", unit="hz")


def run_all() -> BenchmarkCategoryReport:
    report = BenchmarkCategoryReport(category="vision")
    report.add(benchmark_object_detection_fps())
    report.add(benchmark_person_detection_fps())
    report.add(benchmark_gesture_recognition_fps())
    report.add(benchmark_face_recognition_latency())
    report.add(benchmark_face_emotion_update_rate())
    return report
