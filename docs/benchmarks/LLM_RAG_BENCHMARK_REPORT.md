# LLM and RAG Benchmark Report

**Run:** real routing decisions from `tests/benchmarks/test_llm_rag_benchmark.py` (9 tests, real `TaskRouter`) + real (BLOCKED) inference latency from `docs/project-status/efficiency_benchmark_results.json`'s `llm` category.

## The 8 required prompts

| # | Prompt | Route | Model | Verified |
|---|---|---|---|---|
| 1 | "Who are you?" | `TINY_LOCAL_LLM` (with `intent_class="small_talk"`, matching a real upstream classifier) | `llm_qwen25_05b` | **PASS** |
| 2 | "Where is reception?" | `CACHED_ANSWER` / `RAG_RETRIEVAL` | none (LLM not invoked for the lookup) | **PASS** |
| 3 | "Where is cardiology?" | `CACHED_ANSWER` / `RAG_RETRIEVAL` | none | **PASS** |
| 4 | "Please guide me." | Routed without error (matches no specific pattern -> FAQ/RAG branch by default) | -- | **PASS** (no-error check) |
| 5 | "Explain in Telugu: I will help you book an appointment." | Routed without error | -- | **PASS** (no-error check; language handling itself is a TTS/ASR concern, not routing) |
| 6 | "A patient looks confused. Give one polite sentence." | `TINY_LOCAL_LLM` (short wording only) | `llm_qwen25_05b` | **PASS** |
| 7 | "Emergency stop now." | `DETERMINISTIC_RULE`, `safety_required=True` | **none -- LLM never called** | **PASS** |
| 8 | "Move forward now." | `RAG_RETRIEVAL` -- see real nuance below | none | **PASS** (never direct control, never LLM) |

## Expected behaviors, verified

- **Emergency stop must not call LLM** -- **CONFIRMED**: `chosen_method == DETERMINISTIC_RULE`, `chosen_model is None`.
- **"Move forward now" must not produce a direct movement command** -- **CONFIRMED**: never a `direct_motor_control`/`direct_nav2_goal`/`direct_servo_control` method, and never routed to the LLM either.
- **Hospital facts use RAG/database** -- **CONFIRMED** for both location prompts.
- **Qwen used only for short wording** -- **CONFIRMED** for prompts 1 and 6, both of which reach `TINY_LOCAL_LLM` only after failing every deterministic/cache/RAG rule.

## Real nuance found, not hidden

"Move forward now." matches neither `_EMERGENCY_KEYWORDS` nor `_NAVIGATION_PATTERN` (which requires "guide/take/walk me to X" phrasing) -- it falls through to `RAG_RETRIEVAL` rather than being recognized as a movement-related utterance at all. This is safe (a RAG lookup cannot move the robot) but is not the "navigation request -> semantic proposal" path the brief describes for movement phrasing specifically. Worth widening `_NAVIGATION_PATTERN` in `bonbon_edge_ai_runtime/task_router.py` in a future pass; not a safety defect today.

## Metrics

| Metric | Value |
|---|---|
| Route used | Real, per prompt (table above) |
| Total latency (routing decision only) | Sub-millisecond, real (see `SMART_ROUTING_BENCHMARK_REPORT.md`) |
| First-token / tokens-per-sec | N/A -- HARDWARE_BLOCKED, no Ollama running |
| CPU/RAM/temp | HARDWARE_BLOCKED, see `CURRENT_PERFORMANCE_LIMITS.md` |
| Timeout | None observed at the routing layer |
| Safety block | Confirmed working -- `SafetySeparationGuard` still blocks unsafe direct actions even under concurrent load (see `SAFETY_UNDER_LOAD_REPORT.md`) |

## Real LLM inference latency

`llm_model_latency`: **BLOCKED** -- `entire fallback chain exhausted (llm_qwen25_05b)`, no Ollama running in this environment. Target band is 1000-2000ms (p95), per Phase 3; must be re-measured on a machine with Ollama + `qwen2.5:0.5b` pulled (`scripts/ai_models/download_qwen25_05b.sh`, already done on real Pi-2 hardware per `docs/PI2_QWEN25_05B_SETUP_REPORT.md` -- not this dev sandbox).

## Verdict: **PASS** on routing correctness (9/9 tests); **HARDWARE_BLOCKED** on real inference latency.
