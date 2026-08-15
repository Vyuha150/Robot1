# Benchmark Baseline Report

**Run:** `bash scripts/benchmarks/run_all_benchmarks.sh`, 2026-08-15T08:29:37Z, host `Kalyan150` (Windows dev sandbox, no ROS2/Pi/Hailo/Ollama/psutil). Full results: `docs/project-status/efficiency_benchmark_results.json`.

## A note on "baseline" in this repository

This is **not** a before/after-optimization comparison against an unoptimized prior version of BonBon -- the smart-routing + accelerator + caching + safety-separation architecture (`bonbon_edge_ai_runtime`) already existed in this repository before this benchmarking pass began, built and merged in an earlier session. There is no reachable pre-optimization commit this pass safely re-benchmarks (checking out historical commits to run incompatible test infra against was judged too risky for a benchmarking task and was not attempted).

What this report IS: the first real, numeric measurement of the **current, already-optimized architecture**, establishing the reference point every future `scripts/benchmarks/compare_benchmark_runs.py` run compares against going forward. The qualitative pre-optimization state (every request always calling the LLM directly, no cache, no routing, no accelerator abstraction) is documented historically in `docs/EDGE_AI_GAP_ANALYSIS.md` and `docs/DUPLICATE_PIPELINE_AUDIT.md`; the architectural improvement itself is verified directly and exhaustively by `tests/benchmarks/test_task_routing_efficiency.py` (18 tests) rather than by a numeric before/after delta.

## 20 baseline metrics, per Phase 1's required list

| # | Metric | Result | Board |
|---|---|---|---|
| 1 | CPU usage | HARDWARE_BLOCKED -- psutil not installed | dev_sandbox |
| 2 | RAM usage | HARDWARE_BLOCKED -- psutil not installed | dev_sandbox |
| 3 | Temperature | HARDWARE_BLOCKED -- no thermal_zone sysfs path (not a real Pi) | dev_sandbox |
| 4 | Throttling | HARDWARE_BLOCKED -- no Pi throttle register | dev_sandbox |
| 5 | Disk usage | HARDWARE_BLOCKED -- same psutil dependency as CPU/RAM | dev_sandbox |
| 6 | Network latency between 3 Pis | HARDWARE_BLOCKED -- single-machine dev sandbox, no real Pi network. Loopback self-test **PASS** (p95=23.8ms, proves the TCP-RTT probe mechanism itself works) | all |
| 7 | ROS2 topic latency | HARDWARE_BLOCKED -- rclpy not importable | dev_sandbox |
| 8 | Queue size | Not separately measured this run -- camera_queue_size_max_frames=2 is a config target (`config/benchmarks/pi_resource_limits.yaml`), not yet instrumented against a real queue | -- |
| 9 | Dropped frames | HARDWARE_BLOCKED -- needs a real camera stream | ai_pi |
| 10 | Model inference latency | Mixed -- see LLM/ASR/TTS below | ai_pi |
| 11 | ASR latency | HARDWARE_BLOCKED -- `no invoker wired for ASR entry 'asr_degraded_template'` (that specific registry entry has no real invoker; faster-whisper entries do, per `docs/AI_MODEL_BENCHMARK_REPORT.md`) | ai_pi |
| 12 | TTS latency | HARDWARE_BLOCKED -- `no invoker wired for TTS entry 'tts_cached_phrase'` (same reason) | ai_pi |
| 13 | LLM latency | HARDWARE_BLOCKED -- `entire fallback chain exhausted (llm_qwen25_05b)`, no Ollama running | ai_pi |
| 14 | RAG latency | **PASS** (cache path) -- rag_cache_cold p95=0.012ms, rag_cache_warm p95=0.006ms (in-process cache timing only, not full retrieval-with-miss latency) | ai_pi |
| 15 | Object detection FPS | HARDWARE_BLOCKED -- no camera/OpenCV | ai_pi |
| 16 | Gesture recognition FPS | Routing-decision layer **verified real** (p95 < 50ms, see `PERCEPTION_BENCHMARK_REPORT.md`); actual CV FPS HARDWARE_BLOCKED | ai_pi |
| 17 | Face recognition latency | HARDWARE_BLOCKED -- no camera/OpenCV | ai_pi |
| 18 | Affective AI update rate | HARDWARE_BLOCKED (face) / routing layer verified (emotion decision) | ai_pi |
| 19 | Dashboard latency | **Mixed, real finding**: `/api/v1/status` PASS (p95=12.7ms); `/api/v1/data/datasets` **FAIL** (p95=244.7ms, target 100ms); `/api/v1/validation/scenario-families` **FAIL** (p95=170.4ms, target 100ms) | ui_pi |
| 20 | Safety stop latency | Classification layer **PASS** (p95=0.011-0.013ms, target 50ms, both baseline and under simulated load); physical emergency-stop reaction HARDWARE_BLOCKED (needs real Safety Supervisor + motor hardware) | nav_pi / dev_sandbox |

## Headline real finding (not hidden)

Two dashboard endpoints exceed the 100ms `dashboard_status` budget by 1.7-2.4x: `/api/v1/data/datasets` (245ms p95) and `/api/v1/validation/scenario-families` (170ms p95). Both re-parse a YAML/manifest file from disk on every request with no caching. This is a genuine, benchmark-caught bottleneck -- see `docs/benchmarks/FINAL_EFFICIENCY_BENCHMARK_REPORT.md`'s "remaining bottlenecks" section for the recommended fix (memoize the parsed file, invalidate on mtime change), not fixed in this pass to keep this baseline measurement honest and unmodified by the same pass that measured it.

## Command to reproduce

```bash
bash scripts/benchmarks/run_all_benchmarks.sh
```
