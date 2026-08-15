# Perception Benchmark Report (Vision, Gesture, Affective AI)

**Run:** real, from `docs/project-status/efficiency_benchmark_results.json`'s `vision` category (5 metrics, all honestly BLOCKED) + `tests/benchmarks/test_perception_benchmark.py` (12 tests, real routing-layer measurements).

## The 10 required scenarios

| # | Scenario | Result |
|---|---|---|
| 1 | Object detection FPS | HARDWARE_BLOCKED -- no OpenCV/camera device |
| 2 | Person detection FPS | HARDWARE_BLOCKED -- same reason |
| 3 | Multi-person tracking latency | HARDWARE_BLOCKED -- needs a real detection sequence with track continuity across frames; no synthetic substitute would be a real measurement |
| 4 | Gesture recognition FPS | HARDWARE_BLOCKED (CV inference); **routing DECISION latency is real** -- p95 < 50ms over 100 real `route_gesture()` calls |
| 5 | Stop-palm detection latency | Routing layer confirms `stop_palm` is correctly flagged `safety_required=True`; CV detection latency itself HARDWARE_BLOCKED |
| 6 | Pointing gesture latency | Routing layer real (`estimated_latency_ms` populated); CV detection HARDWARE_BLOCKED |
| 7 | Face recognition latency | HARDWARE_BLOCKED -- no OpenCV/camera device |
| 8 | Face emotion update latency | HARDWARE_BLOCKED -- same reason |
| 9 | Human-state fusion update latency | Emotion-routing DECISION latency is real -- p95 < 50ms over 100 real `route_emotion()` calls; full multi-modal fusion latency needs real face+voice+text input, HARDWARE_BLOCKED |
| 10 | Active-person focus efficiency | Routing layer confirmed never routes gesture/emotion decisions to a vision-accelerator method (a category-error check, not a resource-allocation measurement -- that policy lives in `bonbon_perception_efficiency`, out of this file's scope) |

## Metrics

| Metric | Status |
|---|---|
| FPS | HARDWARE_BLOCKED |
| Latency (CV inference) | HARDWARE_BLOCKED |
| Latency (routing decision) | **Real**, sub-50ms p95 |
| Confidence | N/A -- no real inference ran |
| ID switch count | HARDWARE_BLOCKED -- needs real tracking data |
| Stale frame count | HARDWARE_BLOCKED -- needs a real frame stream |
| Dropped frames | HARDWARE_BLOCKED -- same reason |
| CPU/RAM/temp | HARDWARE_BLOCKED, see `CURRENT_PERFORMANCE_LIMITS.md` |
| Hailo/CPU runtime source | Confirmed importable and correctly falls back to CPU/mock (see `ACCELERATOR_BENCHMARK_REPORT.md`) |

## Verdict: **HARDWARE_BLOCKED** for all real CV/FPS/latency numbers (no camera in this environment); **PASS** for the routing/decision layer, which is real and fast. Re-run on a Pi with a connected OAK-D camera for the CV-side numbers.
