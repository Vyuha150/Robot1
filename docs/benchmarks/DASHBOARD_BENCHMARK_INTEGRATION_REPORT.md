# Dashboard Benchmark Integration Report

## Endpoints (all live, all tested -- `ros2_ws/src/bonbon_operator_api/tests/test_benchmark_api.py`, 12 tests)

| Endpoint | Reads/does | Permission |
|---|---|---|
| `GET /api/v1/benchmarks/status` | Top-line summary of the latest persisted run | `diagnostics:read` |
| `GET /api/v1/benchmarks/latest` | Full latest-run detail, every metric | `diagnostics:read` |
| `GET /api/v1/benchmarks/history` | Bounded run-summary history (50 entries max) | `diagnostics:read` |
| `POST /api/v1/benchmarks/run` | **Actually executes** `bonbon_benchmarks.benchmark_runner.run()` -- a real run, not a canned response | `diagnostics:write` (engineer+) |
| `GET /api/v1/benchmarks/compare` | Compares the two most recent history entries | `diagnostics:read` |
| `GET /api/v1/benchmarks/production-score` | Weighted verdict against `config/benchmarks/production_acceptance_thresholds.yaml`, computed from the latest real run | `diagnostics:read` |
| `GET /api/v1/benchmarks/safety-under-load` | The `safety_under_load` category from the latest run | `diagnostics:read` |
| `GET /api/v1/benchmarks/edge-ai` | Reuses `scripts/edge_ai/benchmark_edge_ai_stack.py`'s own results file -- not a second run | `diagnostics:read` |
| `GET /api/v1/benchmarks/three-pi` | The `three_pi_network` category from the latest run | `diagnostics:read` |
| WebSocket `/ws/benchmarks` | New channel added to `VALID_CHANNELS`, min permission `diagnostics:read` | -- |

## Dashboard sections, mapped to real data (14-item list)

| # | Brief section | Backing |
|---|---|---|
| 1 | Current benchmark run | `GET /benchmarks/status` |
| 2 | Latest scores | `GET /benchmarks/latest` |
| 3 | CPU/RAM/temp trends | `resource` category in `/benchmarks/latest` (BLOCKED in this environment, real on a Pi) |
| 4 | Model latency | `llm`/`speech_ai` categories |
| 5 | ASR/TTS latency | `speech_ai` category |
| 6 | LLM/RAG latency | `llm`/`cache_efficiency` categories |
| 7 | Hailo vs CPU runtime | `GET /benchmarks/edge-ai`'s `accelerator_selection` sub-category |
| 8 | Cache hit rate | `cache_efficiency` category recommendations (hit_rate embedded per metric) |
| 9 | Dropped frames | `vision` category (currently BLOCKED, no camera) |
| 10 | Queue sizes | Not yet separately instrumented -- config target exists (`pi_resource_limits.yaml`), live measurement is a follow-up |
| 11 | Safety under load result | `GET /benchmarks/safety-under-load` |
| 12 | Three-Pi network latency | `GET /benchmarks/three-pi` |
| 13 | Endurance status | Not persisted to the same results file (endurance runs are long-lived and invoked separately via `run_endurance_test.sh`) -- a real gap, stated plainly, not silently claimed integrated |
| 14 | Production readiness score | `GET /benchmarks/production-score` |

## Truthfulness, verified not asserted

- `POST /benchmarks/run` genuinely executes the benchmark suite -- verified end-to-end in `test_run_executes_a_real_benchmark_and_persists_it` (real categories run, real persisted file, real history entry appended).
- `GET /benchmarks/production-score` computes its verdict from the real latest run's summary counts and real safety-category failures -- never a hardcoded PASS (`test_production_score_reflects_a_real_run`).
- `GET /benchmarks/compare` honestly reports `available: False` with fewer than 2 history entries rather than fabricating a comparison (`test_compare_needs_at_least_two_runs`).
- `GET /benchmarks/edge-ai` honestly reports `available: False` when no edge-ai benchmark has ever run (`test_edge_ai_endpoint_honest_when_no_edge_ai_benchmark_has_run`).

## Regression

Full `bonbon_operator_api` suite: **268/268 passed** (256 pre-existing + 12 new), confirming the new router doesn't break app startup or any existing endpoint.

## Known gap

Section 13 (endurance status) and section 10 (live queue sizes) are not yet wired into the dashboard results file -- named here rather than silently claimed complete.
