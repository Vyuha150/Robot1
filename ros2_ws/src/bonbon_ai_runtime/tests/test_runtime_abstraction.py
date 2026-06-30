"""Tests for the bonbon_ai_runtime abstraction.

All pass with NO accelerator hardware and NO hailort/onnxruntime/tensorrt
installed — Hailo presence is mocked via the injectable detector and a fake
infer-factory. This is the core requirement: Hailo is optional, the dev/CI
machine has none, and the tests must still be green.
"""

from __future__ import annotations

import numpy as np
from bonbon_ai_runtime import (
    CPUONNXRuntime,
    HailoDeviceDetector,
    HailoRuntime,
    InferenceMetricsCollector,
    MockRuntime,
    ModelCompatibilityChecker,
    ModelRuntimeHealthMonitor,
    RuntimeKind,
    RuntimeMode,
    RuntimeSelector,
    RuntimeSpec,
    RuntimeStatus,
    TensorRTRuntime,
)


def _frame():
    return np.zeros((640, 640, 3), dtype=np.uint8)


# ── MockRuntime ─────────────────────────────────────────────────────────────
class TestMockRuntime:
    def test_always_available(self):
        assert MockRuntime().is_available().available is True

    def test_infer_and_health(self):
        m = MockRuntime()
        m.load_model("")
        out = m.infer(_frame())
        assert out.ok
        assert out.latency_ms >= 0
        h = m.health()
        assert h.status == RuntimeStatus.READY
        assert h.model_loaded is True
        assert h.total_inferences == 1

    def test_benchmark(self):
        b = MockRuntime().benchmark(runs=10)
        assert b.runs == 10
        assert b.fps > 0
        assert b.failures == 0


# ── HailoDeviceDetector (mocked) ────────────────────────────────────────────
class TestHailoDeviceDetector:
    def test_no_device_no_runtime(self):
        det = HailoDeviceDetector(runner=lambda c: None, import_probe=lambda m: False)
        d = det.detect()
        assert d.device_present is False
        assert d.runtime_available is False
        assert d.usable is False

    def test_device_via_hailortcli_scan(self):
        def runner(cmd):
            if cmd[0] == "hailortcli":
                return (0, "Hailo-8L device found at 0000:01:00.0")
            return None

        det = HailoDeviceDetector(runner=runner, import_probe=lambda m: True)
        d = det.detect()
        assert d.device_present is True
        assert d.usable is True

    def test_device_via_lspci_fallback(self):
        def runner(cmd):
            if cmd[0] == "lspci":
                return (0, "01:00.0 Co-processor: Hailo Technologies Ltd. Hailo-8")
            return None  # hailortcli absent

        det = HailoDeviceDetector(runner=runner, import_probe=lambda m: True)
        assert det.device_present() is True

    def test_device_present_but_runtime_missing(self):
        det = HailoDeviceDetector(
            runner=lambda c: (0, "hailo") if c[0] == "hailortcli" else None,
            import_probe=lambda m: False,
        )
        d = det.detect()
        assert d.device_present is True
        assert d.runtime_available is False
        assert d.usable is False
        assert "not installed" in d.detail.lower()


# ── HailoRuntime (mocked) ───────────────────────────────────────────────────
def _present_detector():
    return HailoDeviceDetector(
        runner=lambda c: (0, "Hailo-8L") if c[0] == "hailortcli" else None,
        import_probe=lambda m: True,
    )


def _absent_detector():
    return HailoDeviceDetector(runner=lambda c: None, import_probe=lambda m: False)


class TestHailoRuntime:
    def test_unavailable_without_hardware(self):
        rt = HailoRuntime(detector=_absent_detector())
        assert rt.is_available().available is False
        # load must fail gracefully, not raise
        assert rt.load_model("models/hailo/yolo.hef") is False
        assert rt.health().status == RuntimeStatus.UNAVAILABLE

    def test_hef_path_validation_rejects_wrong_extension(self):
        rt = HailoRuntime(detector=_present_detector())
        res = rt.validate_model_path("models/onnx/yolo.onnx")
        assert res.compatible is False
        assert ".hef" in res.reason

    def test_loads_and_infers_with_mocked_device(self, tmp_path):
        hef = tmp_path / "yolo.hef"
        hef.write_bytes(b"fake-hef")

        def fake_factory(path):
            # stand-in for a real HailoRT inference callable
            return lambda tensor: [np.zeros((0, 6), dtype=np.float32)]

        rt = HailoRuntime(detector=_present_detector(), infer_factory=fake_factory)
        assert rt.is_available().available is True
        assert rt.load_model(str(hef)) is True
        out = rt.infer(_frame())
        assert out.ok
        assert rt.health().status == RuntimeStatus.READY

    def test_inference_timeout_is_graceful(self, tmp_path):
        import time

        hef = tmp_path / "yolo.hef"
        hef.write_bytes(b"x")

        def slow_factory(path):
            def _slow(tensor):
                time.sleep(0.3)
                return [np.zeros((0, 6), np.float32)]

            return _slow

        rt = HailoRuntime(detector=_present_detector(), infer_factory=slow_factory)
        rt.load_model(str(hef))
        out = rt.infer(_frame(), timeout_ms=20)
        assert out.timed_out is True
        assert out.ok is False  # never raises, just reports

    def test_preprocess_postprocess_hooks(self, tmp_path):
        hef = tmp_path / "y.hef"
        hef.write_bytes(b"x")
        calls = {"pre": 0, "post": 0}

        def pre(frame):
            calls["pre"] += 1
            return frame

        def post(out):
            calls["post"] += 1
            return out

        rt = HailoRuntime(
            detector=_present_detector(),
            preprocess_fn=pre,
            postprocess_fn=post,
            infer_factory=lambda p: (lambda t: [np.zeros((0, 6), np.float32)]),
        )
        rt.load_model(str(hef))
        out = rt.postprocess(rt.infer(rt.preprocess(_frame())))
        assert calls["pre"] == 1 and calls["post"] == 1
        assert out.ok


# ── ModelCompatibilityChecker ───────────────────────────────────────────────
class TestModelCompatibility:
    def test_hailo_needs_hef(self):
        assert ModelCompatibilityChecker.is_format_compatible(RuntimeKind.HAILO, "m.hef") is True
        assert ModelCompatibilityChecker.is_format_compatible(RuntimeKind.HAILO, "m.onnx") is False

    def test_cpu_needs_onnx(self):
        assert ModelCompatibilityChecker.is_format_compatible(RuntimeKind.CPU, "m.onnx") is True
        assert ModelCompatibilityChecker.is_format_compatible(RuntimeKind.CPU, "m.hef") is False

    def test_mock_accepts_anything(self):
        assert ModelCompatibilityChecker.is_format_compatible(RuntimeKind.MOCK, "whatever") is True

    def test_missing_file_is_incompatible(self):
        r = ModelCompatibilityChecker.check(RuntimeKind.HAILO, "/nonexistent/model.hef")
        assert r.compatible is False
        assert "not found" in r.reason


# ── RuntimeSelector ─────────────────────────────────────────────────────────
class TestRuntimeSelector:
    def test_prefers_hailo_when_available(self, tmp_path):
        hef = tmp_path / "yolo.hef"
        hef.write_bytes(b"x")

        def factory(kind):
            if kind == RuntimeKind.HAILO:
                return HailoRuntime(
                    detector=_present_detector(),
                    infer_factory=lambda p: (lambda t: [np.zeros((0, 6), np.float32)]),
                )
            return MockRuntime()

        sel = RuntimeSelector(factory=factory)
        spec = RuntimeSpec(
            mode=RuntimeMode.AUTO,
            runtime_priority=[RuntimeKind.HAILO, RuntimeKind.CPU, RuntimeKind.MOCK],
            model_paths={RuntimeKind.HAILO: str(hef)},
        )
        res = sel.select(spec)
        assert res.selected_kind == RuntimeKind.HAILO
        assert res.fallback_active is False

    def test_falls_back_to_cpu_when_hailo_absent(self, tmp_path):
        onnx = tmp_path / "yolo.onnx"
        onnx.write_bytes(b"x")

        class _FakeCPU(MockRuntime):
            kind = RuntimeKind.CPU

            @property
            def name(self):
                return "cpu_onnx"

        def factory(kind):
            if kind == RuntimeKind.HAILO:
                return HailoRuntime(detector=_absent_detector())
            if kind == RuntimeKind.CPU:
                # Pretend CPU/ONNX is available + loads (real onnxruntime not
                # installed here, so substitute a compatible stand-in).
                return _FakeCPU()
            return MockRuntime()

        # CPU stand-in claims .onnx compatibility via the checker, so give it
        # a real .onnx path.
        sel = RuntimeSelector(factory=factory)
        spec = RuntimeSpec(
            mode=RuntimeMode.AUTO,
            runtime_priority=[RuntimeKind.HAILO, RuntimeKind.CPU, RuntimeKind.MOCK],
            model_paths={RuntimeKind.CPU: str(onnx)},
        )
        res = sel.select(spec)
        # Hailo absent → CPU stand-in is compatible+available+loads.
        assert res.selected_kind == RuntimeKind.CPU
        assert res.fallback_active is True
        assert "hailo" in res.fallback_reason.lower()

    def test_fail_open_to_mock_when_nothing_loads(self):
        # No model paths, no hardware → everything fails → mock fallback.
        sel = RuntimeSelector()
        res = sel.select(RuntimeSpec(mode=RuntimeMode.AUTO, fail_open_to_degraded_mode=True))
        assert res.selected_kind == RuntimeKind.MOCK
        assert res.fallback_active is True
        assert res.runtime.health().model_loaded is True

    def test_explicit_mock_mode(self):
        res = RuntimeSelector().select(RuntimeSpec(mode=RuntimeMode.MOCK))
        assert res.selected_kind == RuntimeKind.MOCK
        assert res.fallback_active is False

    def test_selection_serialises_for_dashboard(self):
        res = RuntimeSelector().select(RuntimeSpec(mode=RuntimeMode.AUTO))
        d = res.to_dict()
        assert "selected_runtime" in d
        assert "fallback_active" in d
        assert isinstance(d["chain"], list) and d["chain"]


# ── TensorRTRuntime (graceful unavailable) ──────────────────────────────────
class TestTensorRTRuntime:
    def test_unavailable_without_sdk(self):
        rt = TensorRTRuntime()
        # tensorrt is not installed on the dev/CI machine.
        avail = rt.is_available()
        assert avail.available is False
        assert rt.load_model("model.engine") is False


# ── CPUONNXRuntime (graceful unavailable without onnxruntime) ───────────────
class TestCPUONNXRuntime:
    def test_reports_availability_honestly(self):
        rt = CPUONNXRuntime()
        avail = rt.is_available()
        # Either onnxruntime is installed (available) or not — but it must
        # answer without raising and infer must fail gracefully when unloaded.
        out = rt.infer(_frame())
        assert out.ok is False  # no model loaded
        assert isinstance(avail.available, bool)


# ── Metrics + health helpers ────────────────────────────────────────────────
class TestMetricsAndHealth:
    def test_metrics_rolling_stats(self):
        mc = InferenceMetricsCollector(window=10)
        for ms in (10, 20, 30):
            mc.record(ms)
        mc.record(0, timed_out=True)
        snap = mc.snapshot()
        assert snap.total == 4
        assert snap.timeouts == 1
        assert snap.mean_ms == 20.0
        assert snap.fps > 0

    def test_health_degrades_after_consecutive_failures(self):
        h = ModelRuntimeHealthMonitor(degrade_after_consecutive=3)
        h.mark_model_loaded(True)
        assert h.status(available=True) == RuntimeStatus.READY
        for _ in range(3):
            h.record_inference(False)
        assert h.status(available=True) == RuntimeStatus.DEGRADED
        h.record_inference(True)  # one good run recovers
        assert h.status(available=True) == RuntimeStatus.READY

    def test_health_failed_when_load_failed(self):
        h = ModelRuntimeHealthMonitor()
        h.mark_model_loaded(False)
        assert h.status(available=True) == RuntimeStatus.FAILED

    def test_health_uninitialised_before_load(self):
        h = ModelRuntimeHealthMonitor()
        assert h.status(available=True) == RuntimeStatus.UNINITIALISED
