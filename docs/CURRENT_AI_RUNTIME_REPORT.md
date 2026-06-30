# Current AI Runtime Report (Phase 1 — read-only)

**Date:** 2026-06-30
**Scope:** Deployment requirement #7 — *AI HAT must be used for compatible
vision inference workloads.*

## How vision inference is selected and run today

`bonbon_vision/nodes/vision_node.py::_build_detector()` is the entire runtime
selection logic:

```python
backend = self._cfg.detector.backend     # ROS2 param "detector_backend"
if backend == "yolo":
    from ..detectors.yolo_detector import YoloDetector   # ultralytics
    return YoloDetector(...)
elif backend == "mock":
    return MockDetector(...)
else:
    return MockDetector(...)              # unknown → mock
```

Two real backends: `yolo` and `mock`. There is **no** runtime abstraction,
no device/accelerator selector, no fallback chain — just an if/elif on a
string parameter.

## What `YoloDetector` actually supports

- Loads via `ultralytics.YOLO(model_path)`; its docstring lists `.pt`
  (PyTorch), `.engine` (TensorRT), `.onnx` (ONNX Runtime).
- Device selection is `cfg.detector.device` (`""`=auto, `"cpu"`, `"cuda:0"`,
  `"mps"`) passed straight to ultralytics.
- **Its own docstring:** *"Recommended models for the Jetson Orin Nano …
  `yolo export model=yolov8n.pt format=engine device=0 half=True`"* — the
  detector was designed for **NVIDIA Jetson + TensorRT**, with CUDA the
  intended accelerator.

## Hailo support: none

`grep -rlnw 'hailo|Hailo|HAILO' --include=*.py` across all 736 Python files →
**zero matches.** There is:

- No HailoRT (`.hef`) loading path. Hailo's toolchain compiles ONNX → `.hef`,
  and `.hef` files execute only via the `hailort` Python runtime — **not**
  through ultralytics or onnxruntime. Pointing `detector_model_path` at a
  `.hef` would fail in `ultralytics.YOLO()`.
- No Hailo device detection, no `hailortcli`/PCIe probing in any node.
- No NPU telemetry source — so the dashboard has nothing to display for "AI
  HAT" status (confirmed in the previous deployment pass).

## Consequence on a Raspberry Pi 5 + AI HAT

With the code as-is, the only working vision backends on a Pi are:

- `yolo` with a `.pt`/`.onnx` model running on the **ARM CPU** (no CUDA on a
  Pi; TensorRT `.engine` files are CUDA-only and won't load), or
- `mock`.

So the AI HAT sits idle and YOLO inference runs on the Pi's CPU — directly
violating requirement #7 and feeding the CPU-overload risk (#5/#8). The
existing Pi deployment doc even acknowledges this implicitly, recommending
"the smallest YOLO model and a low detection_rate_hz" to survive on CPU.

## What's already good (the seam to build on)

- `BaseDetector(ABC)` is a clean interface: `_detect_impl(bgr) → list[ObjectDetection]`,
  `load_model()`, plus built-in **timeout**, **degraded mode**
  (`_enter_degraded`, `is_degraded`), consecutive-timeout tracking, and a
  worker-thread executor. A Hailo path slots in as either a new
  `BaseDetector` subclass or (cleaner, per the task) a separate runtime the
  detector delegates to.
- The degraded-mode + CPU-fallback contract requirement #12 needs **already
  exists** at the `BaseDetector` level — a Hailo runtime that fails to init
  can fall back without new safety machinery.

## Required outcome (implemented in Phase 3)

A `bonbon_ai_runtime` package providing `VisionModelRuntimeInterface` with
`CPUONNXRuntime` / `TensorRTRuntime` / `HailoRuntime` / `MockRuntime`
implementations and a `RuntimeSelector` (auto / cpu / hailo / tensorrt /
mock) that prefers Hailo when detected, falls back to CPU with a logged,
dashboard-visible reason otherwise, and **never makes Hailo mandatory** on a
development machine (all paths mockable, tests green without hardware).
