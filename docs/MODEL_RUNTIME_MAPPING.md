# Model Runtime Mapping

How BonBon decides which inference runtime runs each vision model.
Single source of truth: [`config/runtime/model_runtime.yaml`](../config/runtime/model_runtime.yaml),
consumed by `bonbon_ai_runtime.RuntimeSelector`.

## The mapping

| Model | Runtime priority | Hailo (.hef) | CPU (.onnx) | Pi FPS cap |
|---|---|---|---|---|
| object_detection | hailo → cpu → mock | `yolo_object_detection.hef` | `yolo_object_detection.onnx` | 10 |
| person_detection | hailo → cpu → mock | `person_detection.hef` | `person_detection.onnx` | 12 |
| pose_gesture_backbone | hailo → cpu → mock | `pose_backbone.hef` | `pose_backbone.onnx` | 8 |
| face_detection | hailo → cpu → mock | `face_detection.hef` | `face_detection.onnx` | 5 |
| mock_test_model | mock | — | — | 30 |

## How selection works (per model)

`RuntimeSelector.select()` walks the `runtime_priority` list and picks the
**first** runtime that is:

1. **available** — its SDK is importable and (for Hailo) the device is
   detected, and
2. **format-compatible** — the configured model file has the right extension
   (`.hef` for Hailo, `.onnx` for CPU) and exists, and
3. **loads** without error.

The first entry that satisfies all three is selected. If a later entry is
chosen, `fallback_active = true` with a human-readable reason
(`preferred 'hailo' unavailable; using 'cpu'`) that the dashboard shows.

If nothing in the list loads and `fail_open_to_degraded_mode` is true (it is,
on every Pi profile), `MockRuntime` is the guaranteed final fallback so the
vision node stays alive in degraded mode rather than crashing.

## Format rules (enforced by `ModelCompatibilityChecker`)

| Runtime | Loads | Notes |
|---|---|---|
| `hailo` | `.hef` | compiled by the Hailo Dataflow Compiler from ONNX |
| `cpu` | `.onnx` | ONNX Runtime, CPUExecutionProvider |
| `tensorrt` | `.engine` / `.plan` / `.trt` | NVIDIA only; not used on a Pi |
| `mock` | anything (incl. none) | deterministic, always available |

A `.hef` cannot load on CPU and a `.onnx` cannot load on Hailo — the checker
catches a mis-pointed path during selection, so the selector falls through to
the next compatible runtime instead of erroring.

## Profiles

- **Pi + AI HAT:** [`config/runtime/pi_ai_hat.yaml`](../config/runtime/pi_ai_hat.yaml)
  — `mode: auto`, prefers Hailo, `block_production_if_absent: true`.
- **Pi without HAT / Hailo disabled:** [`config/runtime/pi_cpu_fallback.yaml`](../config/runtime/pi_cpu_fallback.yaml)
  — `mode: cpu`, halved FPS caps to protect the ARM CPU.
- **Degraded behaviour:** [`config/runtime/degraded_mode.yaml`](../config/runtime/degraded_mode.yaml)
  — what gets shed and what is never disabled (safety always preserved).

## Validation

`devops/tests/test_runtime_config.py` proves every config parses, every
declared runtime/mode is real, every Hailo model has a `.hef` path, every CPU
model has a `.onnx` path, and degraded mode never lists safety in its
shed-order. Run: `python -m pytest devops/tests/test_runtime_config.py -q`.
