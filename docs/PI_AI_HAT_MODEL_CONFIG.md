# Raspberry Pi AI HAT Model Config

How to point BonBon at the Hailo AI HAT on a production Pi, and how to fall
back to CPU cleanly.

## Pick a runtime profile

| Situation | Profile | Effect |
|---|---|---|
| Pi 5 + AI HAT (Hailo) present | [`config/runtime/pi_ai_hat.yaml`](../config/runtime/pi_ai_hat.yaml) | `mode: auto`, prefers Hailo, blocks production readiness if the device is absent |
| Pi 5, no HAT (or Hailo disabled) | [`config/runtime/pi_cpu_fallback.yaml`](../config/runtime/pi_cpu_fallback.yaml) | `mode: cpu`, halved FPS caps |
| sim / dev / CI | (default) `mode: auto` → falls through to mock | no model files needed |

The vision node reads the active profile + the per-model mapping in
`config/runtime/model_runtime.yaml`.

## Wire it to bonbon_vision (integration point)

`bonbon_ai_runtime` is the tested foundation; the thin adapter that makes
`vision_node` use it is the documented next step. Conceptually:

```python
# in vision_node._build_detector(), when detector_backend == "hailo":
from bonbon_ai_runtime import RuntimeSelector, RuntimeSpec, RuntimeMode, RuntimeKind

spec = RuntimeSpec(
    mode=RuntimeMode(self._cfg.runtime_mode),          # "auto" on the Pi
    runtime_priority=[RuntimeKind.HAILO, RuntimeKind.CPU, RuntimeKind.MOCK],
    model_paths={
        RuntimeKind.HAILO: self._cfg.hailo_hef_path,
        RuntimeKind.CPU:   self._cfg.cpu_onnx_path,
    },
)
selection = RuntimeSelector().select(spec)
# selection.runtime is loaded; selection.fallback_active / .fallback_reason
# are published on the AI-runtime dashboard card.
```

The detector wraps `selection.runtime` and supplies the YOLO-specific
preprocess (letterbox) / postprocess (NMS, COCO labels) via the runtime's
`preprocess_fn` / `postprocess_fn` hooks — the runtime stays format-agnostic.

## Required ROS2 / config parameters (Pi)

| Param | Pi value | Meaning |
|---|---|---|
| `detector_backend` | `hailo` (or `auto`) | select the runtime-backed detector |
| `runtime_mode` | `auto` | prefer Hailo, fall back to CPU |
| `hailo_hef_path` | `/opt/bonbon/models/hailo/yolo_object_detection.hef` | compiled model (see HAILO_MODEL_PREPARATION_GUIDE.md) |
| `cpu_onnx_path` | `/opt/bonbon/models/onnx/yolo_object_detection.onnx` | CPU fallback model |
| `detector_timeout_sec` | `0.3` | per-inference timeout (300 ms) |
| `max_fps` | from `model_runtime.yaml` `max_fps_pi` | throttle to protect CPU/thermal |

## Confirm Hailo is actually used (not silently on CPU)

```bash
ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef --runs 50
```
or watch the dashboard **AI runtime** card: `selected runtime = hailo`,
`fallback active = no`. If it shows `fallback active = yes`, the
`reason for fallback` field says exactly why (no device, HailoRT missing,
`.hef` not found, wrong `--hw-arch`, …).

## Production gate

`pi_ai_hat.yaml` sets `block_production_if_absent: true`: a production deploy
that cannot reach the Hailo device is reported **NOT ready** on the dashboard
deployment-readiness card (the robot still perceives via CPU fallback — it
just isn't certified production-ready until the accelerator is confirmed).
