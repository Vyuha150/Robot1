# Hailo Model Preparation Guide

How to produce the `.hef` model files BonBon's `HailoRuntime` loads on the
Raspberry Pi AI HAT. This is a host-side (x86 + Hailo Dataflow Compiler)
workflow — the Pi only *runs* the compiled `.hef`, it does not compile.

> You do NOT need any of this to develop BonBon. Hailo is optional; with no
> `.hef` files the runtime falls back to CPU/ONNX automatically. This guide
> is only for producing the accelerated models for a production Pi.

## Prerequisites (on an x86 Linux host, not the Pi)

- Hailo AI Software Suite (Dataflow Compiler + `hailo` CLI) — from the Hailo
  Developer Zone, matching your HailoRT version on the Pi.
- The source model exported to ONNX (BonBon already produces these for the
  CPU runtime — same `.onnx` is the compiler input).

## Pipeline: ONNX → HAR → quantized HAR → HEF

```bash
# 1. Parse ONNX into a Hailo Archive (HAR). --hw-arch must match the HAT:
#    hailo8 (26 TOPS) or hailo8l (13 TOPS).
hailo parser onnx yolo_object_detection.onnx \
  --hw-arch hailo8l \
  --har-path yolo_object_detection.har

# 2. Optimize + quantize to int8 using a representative calibration set
#    (a few hundred images from the robot's real environment — hospital /
#    hotel / office / home / university frames give the best accuracy).
hailo optimize yolo_object_detection.har \
  --calib-set-path calib_images/ \
  --output-har-path yolo_object_detection_quantized.har

# 3. Compile to the runnable .hef.
hailo compiler yolo_object_detection_quantized.har \
  --hw-arch hailo8l \
  --output-dir models/hailo/
# → models/hailo/yolo_object_detection.hef
```

## Match the HAT variant

| HAT | Hailo part | `--hw-arch` | TOPS |
|---|---|---|---|
| AI HAT (13 TOPS) | Hailo-8L | `hailo8l` | 13 |
| AI HAT+ (26 TOPS) | Hailo-8 | `hailo8` | 26 |

A `.hef` compiled for the wrong `--hw-arch` will fail to load on-device;
`HailoRuntime.load_model()` returns False and the selector falls back to CPU
(visible on the dashboard as `fallback_active`).

## Deploy to the Pi

Copy the compiled `.hef` files to the models root referenced by
`config/runtime/model_runtime.yaml` (default `/opt/bonbon/models/hailo/`):

```bash
scp models/hailo/*.hef pi@robot:/opt/bonbon/models/hailo/
```

## Verify on the Pi (honest, no fake PASS)

```bash
# device + runtime present?
bash scripts/pi_hardware_check.sh           # AI HAT / Hailo section

# does BonBon actually select Hailo and how fast?
ros2 run bonbon_ai_runtime ai_runtime_bench \
  --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef \
  --runs 50
# exit 0 + "selected_kind": "hailo" → Hailo is really in use.
# exit 2 + "selected_kind": "mock"/"cpu" → fell back; read fallback_reason.
```

The benchmark CLI cannot report a Hailo PASS without a real Hailo device —
it reports the *actually selected* runtime.

## Calibration data + privacy

Use representative frames from the deployment environment for quantization,
but treat them under the same privacy rules as any captured imagery
(`bonbon_data_feedback`'s PrivacySafeDataPolicy) — do not commit raw
calibration images to the repo; keep them in a separate, access-controlled
dataset store.
