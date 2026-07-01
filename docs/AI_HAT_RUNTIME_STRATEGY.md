# AI HAT / Hailo Runtime Strategy

The frozen strategy for this release: **never fake Hailo execution if
Hailo hardware is unavailable.** Full implementation report:
[HAILO_RUNTIME_INTEGRATION_REPORT.md](HAILO_RUNTIME_INTEGRATION_REPORT.md).
Model preparation: [HAILO_MODEL_PREPARATION_GUIDE.md](HAILO_MODEL_PREPARATION_GUIDE.md).
Model→runtime mapping: [MODEL_RUNTIME_MAPPING.md](MODEL_RUNTIME_MAPPING.md).

## The abstraction

```
VisionModelRuntimeInterface (ABC)
    ├── HailoRuntime       Pi AI HAT via HailoRT (lazy import + injectable detector)
    ├── CPUONNXRuntime     onnxruntime CPU (lazy import; universal Pi fallback)
    ├── TensorRTRuntime    NVIDIA/Jetson path preserved (lazy import)
    └── MockRuntime        always-available reference + final fail-open target
```

`bonbon_ai_runtime.RuntimeSelector(mode)` — modes: `auto`, `hailo`, `cpu`,
`tensorrt`, `mock`.

## Rules (and how each is enforced)

- **On Pi + AI HAT, `auto` prefers Hailo for supported vision models.**
  `RuntimeSelector` walks `runtime_priority` (default `[hailo, cpu, mock]`)
  and picks the first runtime that is available, format-compatible with
  its configured model, and loads successfully. `config/runtime/pi_ai_hat.yaml`
  sets `preferred_accelerator: hailo`.
- **If Hailo is unavailable, fall back to CPU or degraded mode.** Any
  runtime but the preferred one sets `fallback_active=True` with a stated
  reason (`SelectionResult.fallback_reason`) — surfaced on the dashboard,
  never silent. If nothing loads, `MockRuntime` is the guaranteed final
  fallback so vision keeps publishing (degraded) instead of crashing the
  node — see `config/runtime/pi_cpu_fallback.yaml` and
  `config/runtime/degraded_mode.yaml`.
- **Unsupported models are never forced onto Hailo.**
  `ModelCompatibilityChecker.check(kind, model_path)` validates file
  format (`.hef`→hailo, `.onnx`→cpu, `.engine`→tensorrt) before a runtime
  is even attempted; an incompatible model is skipped in the priority walk,
  not force-loaded.
- **Dashboard shows selected runtime and fallback reason.**
  `GET /api/v1/ai-runtime/status` returns `selected_kind`,
  `fallback_active`, `fallback_reason`, and `is_real_accelerator` (only
  `true` for `hailo`/`tensorrt`) computed from a **live** `RuntimeSelector`
  run — the dashboard cannot show a Hailo PASS that isn't real.
- **Hardware tests are BLOCKED if no actual AI HAT is present.**
  `ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py` uses the
  real `HailoDeviceDetector` (no mock) gated by `BONBON_HAILO_HW_TEST=1`;
  off real hardware the 3 on-device tests **SKIP** with a "BLOCKED — run
  on a Pi 5 + AI HAT" reason, and the 3 no-fake-PASS guards (which run
  everywhere) assert the runtime honestly reports Hailo unavailable and
  that `ai_runtime_bench` exits non-zero on a silent mock fallback.

## Tests (this environment, 33 total)

`ros2_ws/src/bonbon_ai_runtime/tests/test_runtime_abstraction.py` (27) +
`test_hardware_gated.py` (6: 3 SKIP off-hardware, 3 always-run no-fake-
PASS guards) — **30 passed, 3 skipped**, 0 failed.

```bash
python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/ -q

# on a real Pi 5 + AI HAT
BONBON_HAILO_HW_TEST=1 BONBON_HAILO_HEF=/opt/bonbon/models/hailo/yolo_object_detection.hef \
  python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v

ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef --runs 50
```

## What's real vs. what's still BLOCKED

| Layer | Status |
|---|---|
| Runtime abstraction (Hailo/CPU/TensorRT/Mock + selector + fail-open) | **implemented, tested off-hardware** |
| Device detection (`HailoDeviceDetector`) | **implemented, tested with injected + real detector paths** |
| Dashboard visibility (`/ai-runtime/status`, `/ai-runtime/benchmark`) | **implemented, real live data** |
| `bonbon_vision._build_detector()` → `RuntimeSelector` wiring | **not yet done** — documented POST-RELEASE item in [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md); the runtime abstraction is proven independently of this wiring |
| Real Hailo inference on physical hardware | **BLOCKED** — no Pi 5 + AI HAT in this environment |
