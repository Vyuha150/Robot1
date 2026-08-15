# Accelerator (Hailo) Benchmark Report

**Verified by:** `tests/benchmarks/test_accelerator_efficiency.py` (10 tests, real `bonbon_ai_runtime.RuntimeSelector`).

## Environment

`AI_HAT_BENCHMARK = HARDWARE_BLOCKED` -- confirmed directly: `hailortcli` is not on PATH, no Hailo SDK installed, no Hailo device present (this is a Windows dev sandbox, not a Pi with an AI HAT). Every finding below is about the **selection/fallback logic's correctness**, verified without needing the hardware itself, not a fabricated Hailo inference number.

## The 8 required checks

| # | Check | Result |
|---|---|---|
| 1 | Hailo detected yes/no | **No** -- `hailortcli` absent |
| 2 | HailoRT available yes/no | **No** -- confirmed via `RuntimeSelector`'s own attempt chain: Hailo is attempted (not silently skipped) and reports `available=False` |
| 3 | HEF model available yes/no | Reported honestly from `config/runtime/model_runtime.yaml`'s `hailo_hef_path`, whatever it currently holds -- never assumed either way |
| 4 | Vision model selects Hailo when available | Selection-logic verified with an injected always-available Hailo-first priority; real hardware absence means the real outcome here is CPU/mock, which the test asserts as the honest actual result |
| 5 | CPU fallback works when Hailo unavailable | **PASS** -- `RuntimeSelector.select()` with Hailo first in priority still returns a real, usable runtime (`result.runtime is not None`), never a bare failure |
| 6 | Unsupported model is not forced onto Hailo | **PASS** -- a priority list that excludes Hailo entirely never selects it (`all(a.kind != RuntimeKind.HAILO for a in result.chain)`) |
| 7 | Dashboard shows runtime source | **PASS** -- every `SelectionResult` exposes `selected_kind`, `fallback_active`, `fallback_reason`, and the full `chain` (attempt history), which `bonbon_operator_api`'s `/data/*` dashboard summary already surfaces |
| 8 | Hailo failure triggers fallback/degraded mode | **PASS** -- `RuntimeSpec.fail_open_to_degraded_mode` defaults `True`; `select()` never raises when Hailo is unavailable, it always returns a usable fallback runtime |

## Metrics

| Metric | Value | Note |
|---|---|---|
| Hailo inference latency | N/A -- HARDWARE_BLOCKED | No real Hailo device |
| CPU fallback latency | Not separately timed in this pass | Real ONNX/CPU inference latency needs a real model + frame, covered by `bonbon_ai_model_registry`'s vision benchmark case (also currently `NotImplementedError` -- no invoker wired) |
| FPS difference | N/A -- HARDWARE_BLOCKED | Requires both runtimes measured on the same real hardware |
| CPU reduction from using Hailo | N/A -- HARDWARE_BLOCKED | Same reason |
| Fallback reason | Real, observed | `hailo_attempt.reason` (from `RuntimeSelector`'s real attempt chain) reports the exact cause -- e.g. no HailoRT SDK -- not a generic string |

## Verdict: **PASS** on selection-logic correctness, **HARDWARE_BLOCKED** on real Hailo inference numbers. The fallback chain is real and tested; the acceleration benefit itself can only be measured on real Pi + AI HAT hardware.
