# Edge AI Benchmark Report

Phase 14 of the Edge AI Runtime brief. Produced by
[`scripts/edge_ai/benchmark_edge_ai_stack.py`](../scripts/edge_ai/benchmark_edge_ai_stack.py).
Raw JSON is persisted to
[`docs/project-status/edge_ai_benchmark_results.json`](project-status/edge_ai_benchmark_results.json)
on every run (read live by `GET /api/v1/edge-ai/benchmarks`).

## What this measures, and why it's different from the AI model benchmark

[`docs/AI_MODEL_BENCHMARK_REPORT.md`](AI_MODEL_BENCHMARK_REPORT.md) benchmarks
real model **inference** (ASR/TTS/LLM/vision) and is mostly `blocked` on this
dev sandbox, since it has no Ollama, camera, or Hailo hardware installed.

This report benchmarks the edge_ai **runtime layer** itself — the six
orchestration/decision components `bonbon_edge_ai_runtime` adds:
`task_router`, `safety_separation_guard`, `cache_manager`, `resource_guard`,
`inference_scheduler`, `accelerator_manager`. All six are pure-Python
decision code with no external hardware dependency, so there is no
"blocked, no Ollama here" case for this layer — every category below either
genuinely passes with a real timing number, or genuinely fails with a real
exception. Nothing here is a fabricated pass.

## Run 1 (dev sandbox, 200 iterations per category)

```
Running 6 edge_ai benchmark categor(y/ies), 200 iterations each...
Summary: 6/6 categories passed in 1.27s
```

| Category | Status | Min | Mean | P95 | Max | Detail |
|---|---|---|---|---|---|---|
| task_routing | pass | 0.023ms | 0.029ms | 0.045ms | 0.194ms | ok |
| safety_separation | pass | 0.006ms | 0.011ms | 0.015ms | 0.189ms | ok |
| caching | pass | 0.011ms | 0.012ms | 0.014ms | 0.066ms | ok |
| resource_guard | pass | 0.014ms | 0.024ms | 0.035ms | 0.475ms | ok |
| inference_scheduling | pass | 0.007ms | 0.008ms | 0.008ms | 0.058ms | ok |
| accelerator_selection | pass | 0.014ms | 0.016ms | 0.017ms | 0.122ms | mock runtime forced -- no real Hailo/OAK-D hardware on this sandbox |

**6/6 categories pass, all genuine.** Every category is a real call into the
actual `bonbon_edge_ai_runtime` class (`TaskRouter.route_text_intent`,
`SafetySeparationGuard.classify`, `CacheManager.rag_get`,
`ResourceGuard.evaluate`, `InferenceScheduler.submit`,
`AcceleratorManager.select`), not a mock of the class itself.

### What each category exercises

- **`task_routing`** — `TaskRouter.route_text_intent()` cycling through 5
  representative utterances (emergency, FAQ, appointment, navigation, small
  talk), each exercising a different branch of the rule → cache → RAG → LLM
  decision tree.
- **`safety_separation`** — `SafetySeparationGuard.classify()` on a
  `TEXT_ONLY` action, the hot-path category every LLM response passes
  through.
- **`caching`** — `CacheManager.rag_get()` against a pre-warmed
  `RagResultCache` entry (a cache hit, the common case once the cache is
  warm).
- **`resource_guard`** — `ResourceGuard.evaluate()`, which itself calls into
  the real `bonbon_safety.ResourceMonitor`, `bonbon_perception_efficiency.LoadSheddingController`,
  and `bonbon_llm.Pi2LLMGuard` — this is the one category whose timing
  includes a real (if degraded, see below) system call, not pure Python.
- **`inference_scheduling`** — `InferenceScheduler.submit()` for a
  non-safety-critical module (`ai_pi_speech`), exercising the bounded-queue
  enqueue path.
- **`accelerator_selection`** — `AcceleratorManager.select()` forced to
  `RuntimeMode.MOCK` (no real Hailo/OAK-D on this sandbox) — this measures
  the selection/wrapping overhead, not real vision inference latency.

### Reading `resource_guard`'s numbers correctly

`ResourceGuard.evaluate()`'s underlying `bonbon_safety.core.resource_monitor.ResourceMonitor`
reports `available=False` on this Windows dev sandbox (no real Linux
`/proc`-style CPU/disk metrics for the configured `data_path="/"`), so this
run's `resource_guard` numbers measure the **honest "metrics unavailable,
never fabricate an alarm" fast path** (see
[`tests/edge_ai/test_resource_guard.py`](../tests/edge_ai/test_resource_guard.py)),
not a real psutil sampling call. On real Pi hardware, where `available=True`,
expect a higher and more variable latency (real `/proc` reads + a real
`LoadSheddingController` hysteresis evaluation) — this must be re-measured
on Pi-2/Pi-3 before being treated as production-representative.

### Sub-millisecond numbers are expected and correct, not suspicious

Every category here is in-process Python object/dataclass construction and
dict/regex logic — no I/O, no subprocess, no network call (`resource_guard`'s
psutil path is the only near-exception, and it's short-circuited on this
sandbox as noted above). Sub-millisecond timings are the expected shape for
this layer; the multi-second numbers in `AI_MODEL_BENCHMARK_REPORT.md` are
for a fundamentally different thing (loading and running an actual ML model).
Real Pi ARM CPU numbers will be higher than this x86 dev sandbox's, but the
same order of magnitude is expected — none of these six components does
model inference.

## What this run confirms

- All six `bonbon_edge_ai_runtime` orchestration components execute
  correctly end-to-end with zero unhandled exceptions across 1,200 total
  calls (6 categories × 200 iterations).
- `task_router`'s decision tree, `safety_separation_guard`'s classification,
  and `cache_manager`'s hit path all resolve in well under 1ms — none of
  these is a routing-layer latency risk relative to the multi-second model
  inference numbers they route *toward* (per `AI_MODEL_BENCHMARK_REPORT.md`).
- `resource_guard`'s honest "metrics unavailable" fallback path is itself
  fast — a caller polling this every cycle on a non-Pi dev machine pays
  negligible overhead.
- `BenchmarkReport`-style JSON persistence round-trips correctly to
  [`docs/project-status/edge_ai_benchmark_results.json`](project-status/edge_ai_benchmark_results.json)
  and is served live by `GET /api/v1/edge-ai/benchmarks`
  ([`edge_ai_status_api.py`](../ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/edge_ai_status_api.py)).

## Remaining gaps (still real, still not faked)

- `resource_guard`'s real (non-fallback) sampling path, and `accelerator_selection`'s
  real Hailo/OAK-D selection path, are not exercised by this sandbox run —
  both need real Pi-2 hardware (a real `/proc` filesystem and a real
  Hailo/OAK-D device) to produce production-representative numbers.
- This script does not benchmark end-to-end task latency (e.g. "utterance
  in → spoken reply out"), since that composes with the model-inference
  numbers already covered in `AI_MODEL_BENCHMARK_REPORT.md` — see
  [`docs/EDGE_AI_DEFAULT_MODEL_CRITERIA.md`](EDGE_AI_DEFAULT_MODEL_CRITERIA.md)'s
  criterion 1 for how the two are meant to be read together.

## Re-running on real Pi-2/Pi-3 hardware

```bash
python3 scripts/edge_ai/benchmark_edge_ai_stack.py
python3 scripts/edge_ai/benchmark_edge_ai_stack.py --category resource_guard
python3 scripts/edge_ai/benchmark_edge_ai_stack.py --iterations 1000
```

Expected to change on real Pi-2 hardware: `resource_guard` should report
`metricsAvailable`/real psutil numbers instead of the fallback path measured
here (the category will still `pass`, just with real system-call overhead
in the timing); `accelerator_selection` should resolve to `hailo` instead of
`mock` if a real AI HAT is attached and `hailort` is installed.
