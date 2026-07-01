# AI HAT Runtime Report

Status snapshot for the Hailo/AI HAT blocker at finalization time. Full
design/rules: [AI_HAT_RUNTIME_STRATEGY.md](AI_HAT_RUNTIME_STRATEGY.md).
Original implementation writeup: [HAILO_RUNTIME_INTEGRATION_REPORT.md](HAILO_RUNTIME_INTEGRATION_REPORT.md).

## Verdict: IMPLEMENTED and tested off-hardware; real on-device run BLOCKED

| Item | Status |
|---|---|
| `VisionModelRuntimeInterface` + `HailoRuntime`/`CPUONNXRuntime`/`TensorRTRuntime`/`MockRuntime` | **PASS** — implemented, `bonbon_ai_runtime` package |
| `RuntimeSelector(auto\|hailo\|cpu\|tensorrt\|mock)` | **PASS** — 27 unit tests |
| `HailoDeviceDetector` (real + injectable) | **PASS** — tested with both a real (absent-on-this-machine) and injected detector |
| Unsupported models never forced onto Hailo | **PASS** — `ModelCompatibilityChecker` gates by file extension before any load attempt |
| Dashboard shows selected runtime + fallback reason | **PASS** — `GET /api/v1/ai-runtime/status`, `GET /api/v1/ai-runtime/benchmark`, `GET /api/v1/dashboard/summary`, `/ws/ai-runtime` |
| Hardware tests BLOCKED without real AI HAT | **PASS** — `test_hardware_gated.py`'s 3 on-device tests SKIP with a stated reason; verified in this environment (no Hailo present) |
| Real Hailo inference on physical hardware | **BLOCKED** — no Pi 5 + AI HAT in this environment |
| `bonbon_vision._build_detector()` → `RuntimeSelector` wiring | **PARTIAL** — the abstraction is proven; live vision node doesn't yet consume it (documented POST-RELEASE item) |

## Commands

```bash
python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/ -q          # 30 passed, 3 skipped (this env)
bash scripts/pi_hardware_check.sh                                  # on a real Pi
BONBON_HAILO_HW_TEST=1 BONBON_HAILO_HEF=/opt/bonbon/models/hailo/yolo_object_detection.hef \
  python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v
ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef --runs 50
```
