# Current Performance Limits

What this dev-sandbox measurement run can and cannot tell you, stated plainly before any other benchmark doc is read.

## Hard limits of this environment

| Limit | Cause | What it blocks |
|---|---|---|
| No `psutil` | Not installed | Real CPU%/RAM/disk sampling (`resource` category) |
| No thermal_zone sysfs | Windows, not a real Pi | CPU temperature, thermal throttling |
| No `rclpy` | No ROS2 installation | Topic pub/sub latency, real Safety Supervisor e-stop reaction |
| No Hailo SDK/`hailortcli` | No AI HAT hardware | Real Hailo inference latency/FPS |
| No camera / OpenCV | No `cv2`, no camera device | Object/person/gesture-FPS, face recognition latency |
| No Ollama running | Not installed/started | Real LLM inference latency |
| No wired ASR/TTS model invoker for every registry entry | Only faster-whisper/Piper-provider entries have real invokers; `asr_degraded_template`/`tts_cached_phrase` don't | Those two specific benchmark cases (other entries in the registry could still be benchmarked by pointing the harness at them) |
| Single machine | Dev sandbox, not 3 physical Pis | Real inter-Pi network latency, cross-Pi proposal/approval latency, degraded-mode-on-real-Pi-failure |

## What genuinely CAN and WAS measured here, in full

- **Task routing correctness and decision latency** -- real `TaskRouter`, sub-millisecond decisions, 27 passing tests.
- **Safety classification latency, baseline and under simulated concurrent load** -- real `SafetySeparationGuard`, p95 0.011-0.013ms against a 50ms critical budget, verified stable under 2 CPU-spin threads + concurrent cache/router traffic.
- **Cache efficiency** -- real `RagResultCache`/`ResponseCache`/TTS phrase-key lookup, all sub-0.02ms.
- **Dashboard REST/WebSocket latency** -- real FastAPI `TestClient` against the actual app (no network hop, so real UI-Pi-to-AI-Pi latency will be higher than these numbers, but the endpoint's OWN processing cost is real and accurately measured).
- **TCP-RTT network probe mechanism** -- proven correct via a real loopback listener, even though the 3 real Pi pairs are unreachable here.
- **Runtime-selection/accelerator-fallback logic** -- real `RuntimeSelector`, confirmed correct fallback chain without needing real Hailo hardware.

## Ceiling this environment imposes on the final verdict

Because 20 of 33 measured metrics in the full run are `BLOCKED` (not failed -- genuinely unmeasurable here), the final production-readiness verdict in `docs/benchmarks/FINAL_EFFICIENCY_BENCHMARK_REPORT.md` cannot be an unconditional PASS. It is explicitly `PARTIAL`, with every hardware-gated item named individually -- see that report's "hardware tests passed/blocked" section for the complete accounting, and `scripts/benchmarks/run_hardware_benchmarks.sh` for exactly which command closes each gap once run on real target hardware.
