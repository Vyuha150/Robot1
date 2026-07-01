# Pi Efficiency Profile Report (Phase 5, updated during Finalization Mode)

How BonBon reduces load on a Raspberry Pi 5 **without** reducing safety.

## The profile

[`config/pi_efficiency_profile.yaml`](../config/pi_efficiency_profile.yaml),
loaded by `bonbon_perception_efficiency.core.pi_efficiency_profile.PiEfficiencyProfile`.
Frozen for this release in
[ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) section 7.

**Priority order (rank 1 = most important = shed last):**

| Rank | Module | Safety-critical |
|---|---|---|
| 1 | safety_supervisor | ✅ never shed |
| 2 | emergency_stop | ✅ |
| 3 | hal | ✅ |
| 4 | lidar_obstacle_safety | ✅ |
| 5 | navigation_safety | ✅ |
| 6 | active_person_tracking | ✅ |
| 7–8 | object / person detection | |
| 9 | gesture_recognition | |
| 10–11 | speech_vad / stt | |
| 12 | human_state_fusion | |
| 13 | tts | |
| 14 | dashboard | |
| 15–16 | rag / llm | |
| 17 | background_emotion | |
| 18 | analytics_logging | shed first |

Under load, modules are shed from the bottom up; the six safety-critical
modules are **never** in the shed order (enforced by `profile.validate()`).

**Pi production FPS caps:** object 8, person-tracking 10, gesture 8, face
emotion 1 (active person only), voice emotion per-segment. **Event-gated:**
STT on VAD, LLM on stable intent, RAG on cache-miss. **Queues** bounded
(vision 4, affective 4, data-feedback 8). **Data writes** batched +
non-blocking.

## Primitives — all already existed, now governed by the profile

| Concern | Primitive | Built |
|---|---|---|
| CPU budget | `LoadSheddingController` + `ResourceMonitor` → `/bonbon/system/resource_usage` | earlier this session |
| Thermal budget | thermal input to `LoadSheddingController` (`cpu_temp_caution_c=75`) | earlier this session |
| Bounded queues | `BoundedInferenceQueue` | earlier this session |
| Stale-frame drop | `StaleFrameDropper` | earlier this session |
| Model timeout | `BaseDetector` + `bonbon_ai_runtime` runtime timeout | existing + Phase 3 |
| Frame-rate throttle | `FrameSamplingManager` (scaled by shed level) | earlier this session |
| Active-person focus | `ActivePersonFocusManager` + `FocusPublishGate` | earlier this session |
| Event STT | VAD-gating in `bonbon_speech` | existing |
| Cached RAG | `ResponseCache` (checked before RAG) | earlier this session |
| LLM timeout | Ollama client timeout | existing |
| Degraded mode | `DegradedModeManager` | earlier this session |

Phase 5's contribution is the **profile that ties them together** into one
priority/limit policy, plus the scenario tests proving the policy holds.

## The 10 scenario tests (all green, no Pi)

`bonbon_perception_efficiency/tests/test_pi_efficiency_scenarios.py`:

1. CPU overload → degraded mode (LoadSheddingController → MINIMAL → sustained → DegradedModeManager).
2. Thermal warning reduces FPS (thermal → scale < 1 → FrameSamplingManager raises sample interval).
3. Hailo unavailable → CPU/mock fallback (RuntimeSelector with absent detector).
4. Inference backpressure never blocks the caller (full BoundedInferenceQueue rejects instantly).
5. Dashboard not shed before the genuinely-optional modules (analytics/background-emotion go first).
6. Safety never shed, even at `modules_to_shed(999)`; `validate()` clean.
7. Background emotion sheds before perception modules.
8. LLM/RAG are event-gated and shed before human-state fusion.
9. Queue never grows unbounded (100 admits, depth ≤ max, drops counted).
10. Stale frames dropped after timeout.

Plus a profile self-consistency test. Run:
`python -m pytest ros2_ws/src/bonbon_perception_efficiency/tests/test_pi_efficiency_scenarios.py -q`.

## Honest scope

The profile is loaded and validated, and every primitive is unit-proven. What
remains hardware-only: confirming the *measured* CPU%, temperature, and FPS on
a live Pi 5 under a real multi-person workload stay within these limits — that
is the BLOCKED row in the final checklist, runnable with `vcgencmd` + `top` +
the `ai_runtime_bench` CLI on the actual robot.

## Finalization-mode correction (2026-07-01)

Ranks 2 and 3 (`emergency_stop`/`hal`) were swapped to match the frozen
architecture doc's literal ordering ("1. Safety Supervisor · 2. Emergency
stop polling · 3. HAL"). This has **zero functional effect** — ranks 1-6
are all `safety_critical: true` and `shed_order()`/`modules_to_shed()`
only ever operate on non-safety-critical ranks (7-18) — but it removes a
real discrepancy between the documented and configured order. Re-verified:
88 `bonbon_perception_efficiency` tests + 71 related production-scenario
tests all still pass after the change.
