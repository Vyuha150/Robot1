"""
tests/benchmarks/bench_inference.py
=====================================
Latency benchmarks for the bonbon_vision inference pipeline.

Benchmarks included
-------------------
1. FrameProcessor (preprocessing only)
   - Normal bright frame
   - Low-light frame (CLAHE enabled)

2. MockDetector (no real inference — measures overhead)
   - 1, 2, 5, 10, 20 objects
   - With depth map vs without

3. FacePipeline (mock backend)
   - Detection only
   - Detection + recognition

4. PrivacyGuard
   - Blur (Gaussian, various kernel sizes)
   - Pixelation

5. End-to-end pipeline
   - preprocess → detect → face → track → privacy

6. Throttler overhead (should be sub-microsecond)

Usage
-----
    python -m tests.benchmarks.bench_inference
    python -m tests.benchmarks.bench_inference --quick
    python -m tests.benchmarks.bench_inference --json results.json

Options
-------
  --quick          Run fewer iterations (for CI smoke test)
  --json PATH      Write results to JSON file
  --warmup N       Warmup iterations before measuring (default 5)
  --iters N        Measurement iterations (default 100)
  --min-hz RATE    Warn if throughput falls below this Hz (default 5.0)
"""

from __future__ import annotations

import argparse
import json

# ── Allow running from repo root without installing ───────────────────────────
import os
import statistics
import sys
import time
import types
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ── Stub ROS2 packages if not available (benchmark runs without a ROS env) ────
def _ros_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


try:
    import rclpy  # noqa
except ImportError:
    _RP = type("ReliabilityPolicy", (), {"RELIABLE": 1, "BEST_EFFORT": 0})
    _DP = type("DurabilityPolicy", (), {"TRANSIENT_LOCAL": 1, "VOLATILE": 0})
    _HP = type("HistoryPolicy", (), {"KEEP_LAST": 0, "KEEP_ALL": 1})
    _LC = type(
        "LifecycleNode",
        (),
        {
            "__init__": lambda s, *a, **k: None,
            "get_logger": lambda s: type(
                "L",
                (),
                {
                    "info": lambda *a: None,
                    "warning": lambda *a: None,
                    "warn": lambda *a: None,
                    "error": lambda *a: None,
                    "debug": lambda *a: None,
                },
            )(),
            "create_timer": lambda *a, **k: None,
            "create_publisher": lambda *a, **k: None,
            "create_subscription": lambda *a, **k: None,
            "declare_parameter": lambda *a, **k: None,
            "get_parameter": lambda s, n: type("P", (), {"value": None})(),
            "get_clock": lambda s: type(
                "C", (), {"now": lambda s: type("N", (), {"to_msg": lambda s: None})()}
            )(),
        },
    )
    _TCR = type("TransitionCallbackReturn", (), {"SUCCESS": 0, "ERROR": 1})
    _ros_stubs = {
        "rclpy": _ros_stub("rclpy", init=lambda *a, **k: None, shutdown=lambda: None),
        "rclpy.lifecycle": _ros_stub(
            "rclpy.lifecycle", LifecycleNode=_LC, TransitionCallbackReturn=_TCR, State=object
        ),
        "rclpy.qos": _ros_stub(
            "rclpy.qos",
            QoSProfile=lambda **kw: None,
            ReliabilityPolicy=_RP,
            DurabilityPolicy=_DP,
            HistoryPolicy=_HP,
        ),
        "geometry_msgs": _ros_stub("geometry_msgs"),
        "geometry_msgs.msg": _ros_stub("geometry_msgs.msg", Point=type("Point", (), {})),
        "sensor_msgs": _ros_stub("sensor_msgs"),
        "sensor_msgs.msg": _ros_stub("sensor_msgs.msg", Image=type("Image", (), {})),
        "std_msgs": _ros_stub("std_msgs"),
        "std_msgs.msg": _ros_stub("std_msgs.msg", Header=type("Header", (), {})),
        "bonbon_msgs": _ros_stub("bonbon_msgs"),
        "bonbon_msgs.msg": _ros_stub(
            "bonbon_msgs.msg",
            DetectedObject=type("DO", (), {}),
            DetectedObjectArray=type("DOA", (), {}),
            ModuleHealth=type("MH", (), {}),
            PersonState=type("PS", (), {}),
            PersonStateArray=type("PSA", (), {}),
        ),
    }
    for _n, _m in _ros_stubs.items():
        sys.modules.setdefault(_n, _m)

from bonbon_vision.config.vision_config import (
    FaceConfig,
    PreprocessConfig,
    PrivacyConfig,
)
from bonbon_vision.detectors.mock_detector import MockDetector
from bonbon_vision.face.face_pipeline import FacePipeline
from bonbon_vision.face.privacy_guard import PrivacyGuard
from bonbon_vision.nodes.vision_node import _SimpleTracker
from bonbon_vision.preprocessing.frame_processor import FrameProcessor
from bonbon_vision.preprocessing.frame_throttler import FrameThrottler

# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class BenchResult:
    name: str
    iters: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    throughput_hz: float
    passed: bool  # True if throughput_hz >= min_hz
    extras: dict = field(default_factory=dict)

    def __str__(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return (
            f"{mark} {self.name:<52s} "
            f"mean={self.mean_ms:6.2f}ms  "
            f"p95={self.p95_ms:6.2f}ms  "
            f"p99={self.p99_ms:6.2f}ms  "
            f"Hz={self.throughput_hz:7.1f}"
        )


# ── Benchmarking harness ──────────────────────────────────────────────────────


def bench(
    name: str,
    fn: Callable,
    iters: int = 100,
    warmup: int = 5,
    min_hz: float = 5.0,
    extras: dict = None,
) -> BenchResult:
    for _ in range(warmup):
        fn()

    times_ms = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        times_ms.append((time.perf_counter() - t0) * 1000.0)

    mean = statistics.mean(times_ms)
    median = statistics.median(times_ms)
    sorted_t = sorted(times_ms)
    p95 = sorted_t[max(0, int(len(sorted_t) * 0.95) - 1)]
    p99 = sorted_t[max(0, int(len(sorted_t) * 0.99) - 1)]

    hz = 1000.0 / mean if mean > 0 else float("inf")

    return BenchResult(
        name=name,
        iters=iters,
        mean_ms=mean,
        median_ms=median,
        p95_ms=p95,
        p99_ms=p99,
        min_ms=min(times_ms),
        max_ms=max(times_ms),
        throughput_hz=hz,
        passed=hz >= min_hz,
        extras=extras or {},
    )


# ── Frame factories ───────────────────────────────────────────────────────────


def _bright(h=480, w=640) -> np.ndarray:
    return np.full((h, w, 3), 120, dtype=np.uint8)


def _dark(h=480, w=640) -> np.ndarray:
    return np.full((h, w, 3), 20, dtype=np.uint8)


def _depth(h=480, w=640, val=2.0) -> np.ndarray:
    return np.full((h, w), val, dtype=np.float32)


# ── Benchmark definitions ─────────────────────────────────────────────────────


def run_all(iters: int, warmup: int, min_hz: float) -> list[BenchResult]:
    results: list[BenchResult] = []

    # ── 1. FrameProcessor ────────────────────────────────────────────────────

    pre_cfg = PreprocessConfig(
        resize_width=640,
        resize_height=480,
        enable_clahe=True,
        brightness_threshold=50.0,
        min_mean_brightness=2.0,
    )
    processor = FrameProcessor(pre_cfg)
    bright = _bright()
    dark_f = _dark()
    depth_map = _depth()

    results.append(
        bench(
            "FrameProcessor: bright frame (CLAHE skip)",
            lambda: processor.process(bright),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )

    results.append(
        bench(
            "FrameProcessor: low-light frame (CLAHE applied)",
            lambda: processor.process(dark_f),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )

    results.append(
        bench(
            "FrameProcessor: bright frame + depth map",
            lambda: processor.process(bright, depth_map),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )

    # ── 2. MockDetector ──────────────────────────────────────────────────────

    for n_obj in [1, 2, 5, 10, 20]:
        detector = MockDetector(num_detections=n_obj)
        results.append(
            bench(
                f"MockDetector: {n_obj:>2d} objects (no depth)",
                lambda d=detector: d.detect(bright),
                iters=iters,
                warmup=warmup,
                min_hz=min_hz,
            )
        )
        detector.shutdown()

    # With depth
    det2 = MockDetector(num_detections=5)
    results.append(
        bench(
            "MockDetector: 5 objects + depth map",
            lambda: det2.detect(bright, depth_m=depth_map),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )
    det2.shutdown()

    # ── 3. FacePipeline (mock backend) ───────────────────────────────────────

    face_cfg = FaceConfig(detect_backend="mock", recognize_backend="mock")
    face_pipe = FacePipeline(face_cfg)

    results.append(
        bench(
            "FacePipeline: mock detect + recognize",
            lambda: face_pipe.run(bright),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )
    face_pipe.shutdown()

    # Privacy mode on
    face_priv = FacePipeline(face_cfg, privacy_mode=True)
    results.append(
        bench(
            "FacePipeline: mock + privacy_mode=True",
            lambda: face_priv.run(bright),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )
    face_priv.shutdown()

    # ── 4. PrivacyGuard ──────────────────────────────────────────────────────

    face_bboxes = [(80, 40, 100, 130), (300, 60, 80, 110)]

    for k in [7, 21, 51]:
        guard = PrivacyGuard(
            PrivacyConfig(
                enabled=True,
                blur_faces=True,
                blur_kernel_size=k,
                pixelate_faces=False,
            )
        )
        results.append(
            bench(
                f"PrivacyGuard: Gaussian blur kernel={k}",
                lambda g=guard: g.anonymise(bright, face_bboxes),
                iters=iters,
                warmup=warmup,
                min_hz=min_hz,
            )
        )

    pixel_guard = PrivacyGuard(
        PrivacyConfig(
            enabled=True,
            blur_faces=False,
            pixelate_faces=True,
            pixelate_block_size=8,
            blur_kernel_size=7,
        )
    )
    results.append(
        bench(
            "PrivacyGuard: pixelation block=8",
            lambda: pixel_guard.anonymise(bright, face_bboxes),
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )

    # ── 5. Tracker (SimpleTracker) ────────────────────────────────────────────

    from bonbon_vision.detectors.base_detector import ObjectDetection

    def _det(i):
        return ObjectDetection(
            class_id=0,
            class_name="person",
            confidence=0.9,
            bbox=(i * 80, 100, 60, 150),
            depth_m=float(i + 1),
        )

    for n_obj in [1, 5, 10, 20]:
        tracker = _SimpleTracker()
        dets = [_det(i) for i in range(n_obj)]
        results.append(
            bench(
                f"_SimpleTracker: {n_obj:>2d} persons update",
                lambda t=tracker, d=dets: t.update(d),
                iters=iters,
                warmup=warmup,
                min_hz=min_hz,
            )
        )

    # ── 6. End-to-end pipeline ────────────────────────────────────────────────

    e2e_processor = FrameProcessor(pre_cfg)
    e2e_detector = MockDetector(num_detections=3)
    e2e_face = FacePipeline(face_cfg)
    e2e_privacy = PrivacyGuard(
        PrivacyConfig(
            enabled=True,
            blur_faces=True,
            blur_kernel_size=21,
        )
    )
    e2e_tracker = _SimpleTracker()

    def _e2e():
        pf = e2e_processor.process(bright)
        if not pf.is_usable:
            return
        det_result = e2e_detector.detect(pf.bgr)
        face_result = e2e_face.run(pf.bgr)
        e2e_tracker.update(det_result.detections)
        e2e_privacy.anonymise(pf.bgr, [f.bbox for f in face_result.faces])

    results.append(
        bench(
            "End-to-end: preprocess→detect→face→track→privacy",
            _e2e,
            iters=iters,
            warmup=warmup,
            min_hz=min_hz,
        )
    )

    e2e_detector.shutdown()
    e2e_face.shutdown()

    # ── 7. FrameThrottler overhead ────────────────────────────────────────────

    throttler = FrameThrottler(target_hz=30.0)
    results.append(
        bench(
            "FrameThrottler: should_process() overhead",
            throttler.should_process,
            iters=iters * 10,
            warmup=warmup,
            min_hz=1_000_000.0,  # should be millions of Hz
        )
    )

    return results


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="bonbon_vision inference latency benchmarks")
    parser.add_argument("--quick", action="store_true", help="Run fewer iterations (CI smoke)")
    parser.add_argument("--json", metavar="PATH", help="Write results to JSON")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iters", type=int, default=100)
    parser.add_argument("--min-hz", type=float, default=5.0, dest="min_hz")
    args = parser.parse_args()

    iters = 20 if args.quick else args.iters
    warmup = 2 if args.quick else args.warmup

    print(f"\n{'=' * 90}")
    print(
        f"  bonbon_vision Latency Benchmarks  "
        f"(iters={iters}, warmup={warmup}, min_hz={args.min_hz})"
    )
    print(f"{'=' * 90}\n")

    results = run_all(iters=iters, warmup=warmup, min_hz=args.min_hz)

    all_pass = True
    for r in results:
        print(r)
        if not r.passed:
            all_pass = False

    n_pass = sum(1 for r in results if r.passed)
    n_total = len(results)
    print(f"\n{'─' * 90}")
    print(f"  Results: {n_pass}/{n_total} benchmarks meet ≥{args.min_hz} Hz target")

    if args.json:
        data = [
            {
                "name": r.name,
                "iters": r.iters,
                "mean_ms": round(r.mean_ms, 3),
                "median_ms": round(r.median_ms, 3),
                "p95_ms": round(r.p95_ms, 3),
                "p99_ms": round(r.p99_ms, 3),
                "min_ms": round(r.min_ms, 3),
                "max_ms": round(r.max_ms, 3),
                "throughput_hz": round(r.throughput_hz, 2),
                "passed": r.passed,
            }
            for r in results
        ]
        with open(args.json, "w") as fh:
            json.dump(data, fh, indent=2)
        print(f"  JSON results written to: {args.json}")

    print()
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
