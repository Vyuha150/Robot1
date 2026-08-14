# Hailo Runtime Integration Report (Phase 3)

**Blocker:** zero Hailo support — vision inference ran on the ARM CPU on a
Pi 5 + AI HAT (the detector was scoped for NVIDIA Jetson/TensorRT). Violated
requirement #7.

## Status: backend IMPLEMENTED + tested (mocked); on-device run is BLOCKED on real hardware

New ROS2 package `bonbon_ai_runtime` (core pure Python, no rclpy). Adds Hailo
as an **optional** runtime WITHOUT removing the CPU/TensorRT paths and
WITHOUT making Hailo mandatory on dev machines.

```
VisionModelRuntimeInterface (ABC)
├── MockRuntime        always-available reference + final fallback
├── CPUONNXRuntime     onnxruntime CPU (lazy import; the Pi universal path)
├── TensorRTRuntime    NVIDIA/Jetson path preserved (lazy import)
└── HailoRuntime       Pi AI HAT via HailoRT (lazy import + injectable detector)

RuntimeSelector(auto|cpu|hailo|tensorrt|mock) — walks runtime_priority,
  picks first available+compatible+loadable; fallback_active+reason on
  anything but the preferred; fail-open to mock so vision never crashes.

HailoDeviceDetector · ModelCompatibilityChecker · ModelRuntimeHealthMonitor
· InferenceMetricsCollector
```

`HailoRuntime` covers all 10 required behaviours: device detection, HailoRT
availability, HEF path validation, preprocess hook, postprocess hook,
inference timeout, warmup, benchmark, health, graceful fallback.

## Optional, never mandatory — the key design property

`hailort` is lazy-imported and the device is probed via an **injectable**
`HailoDeviceDetector`. On a machine with no HAT, `HailoRuntime.is_available()`
returns False and the selector falls back to CPU — without ever importing
hailort or touching hardware. That is exactly why the 27 unit tests + the
"no fake pass" hardware-gated tests pass green on this dev machine.

## Tests

- 27 unit tests (`tests/test_runtime_abstraction.py`): prefers-hailo-when-
  available (mocked device + fake infer-factory), falls-back-to-cpu,
  fail-open-to-mock, HEF validation, graceful timeout, pre/post hooks,
  format-compatibility matrix, metrics rolling stats, health degrade/recover.
- 6 hardware-gated tests (`tests/test_hardware_gated.py`): the 3 on-device
  tests **SKIP** off a real Pi+Hailo with a clear "BLOCKED — run on a Pi 5 +
  AI HAT" reason (never fake PASS); the 3 no-fake-PASS guards run everywhere
  and assert the runtime reports Hailo unavailable + the `ai_runtime_bench`
  CLI exits non-zero on a silent mock fallback.

## On-Pi verification (the BLOCKED rows)

```bash
bash scripts/pi_hardware_check.sh                       # AI HAT / Hailo section
BONBON_HAILO_HW_TEST=1 BONBON_HAILO_HEF=/opt/bonbon/models/hailo/yolo_object_detection.hef \
  python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v
ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef --runs 50
```

## Honest residual

**Update (2026-08-14 re-verification):** the adapter described below as a
future step now exists and is wired —
`bonbon_vision/detectors/runtime_adapter_detector.py`'s
`ObjectDetectorRuntimeAdapter` is constructed by `vision_node._build_detector()`
when `detector.backend == "runtime"`, and is covered by
`ros2_ws/src/bonbon_vision/tests/test_runtime_adapter_detector.py` (6/6
passing). It was not re-verified as done in this doc at the time it was
written, only later. One item remains genuinely open: the shipped
`vision_params.yaml` still defaults `detector.backend` to `"mock"`, not
`"runtime"` — no launch file or compose config sets it to `"runtime"`
anywhere in this repo, so even on a Pi with a real AI HAT installed, this
path is not engaged unless someone explicitly overrides the parameter at
launch. Flipping that default is a deployment-time decision (verify the
CPU-ONNX fallback tier's real resource cost on the target Pi first, since
it's heavier than `mock`), not something to change without hardware to
verify against — left for whoever performs the physical Hailo
installation.

Producing the `.hef` files is HAILO_MODEL_PREPARATION_GUIDE.md.
