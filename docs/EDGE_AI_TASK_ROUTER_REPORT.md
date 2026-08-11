# Edge AI Task Router Report

Phase 15 summary of Phase 4's deliverable:
[`task_router.py`](../ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/task_router.py) —
per [`docs/DUPLICATE_PIPELINE_AUDIT.md`](DUPLICATE_PIPELINE_AUDIT.md), the
single most load-bearing genuinely-new module in this brief: a direct
search confirmed zero prior implementation of any cross-capability task
router existed anywhere in this repo before this pass.

## The 11 methods, and how `TaskRouter` chooses among them

`ChosenMethod` enumerates all 11 the brief names: `DETERMINISTIC_RULE`,
`EXACT_DATABASE_LOOKUP`, `CACHED_ANSWER`, `RAG_RETRIEVAL`,
`TINY_LOCAL_LLM`, `ASR_MODEL`, `TTS_MODEL`, `HAILO_VISION_MODEL`,
`CPU_FALLBACK_MODEL`, `DEGRADED_FALLBACK_TEMPLATE`,
`STAFF_ESCALATION`. `route_text_intent()` walks a fixed cost order —
emergency phrase → navigation request → appointment booking → FAQ
(cache, then RAG) → small talk (tiny local LLM, last resort) — so the
most expensive method is never tried before every cheaper, deterministic
option has been ruled out. `route_gesture()` and `route_emotion()` apply
the same cheapest-safe-choice principle to non-text modalities.

## The 8 required routing examples — all verified

| Input | Routed to | Safety required? |
|---|---|---|
| "help, someone collapsed" | `DETERMINISTIC_RULE` (emergency workflow, staff + Safety Supervisor alerted) | Yes |
| "Where is Cardiology?" | `CACHED_ANSWER` / `RAG_RETRIEVAL` (FAQ) | No |
| "Book appointment with Dr. Rao" | `DETERMINISTIC_RULE` (appointment workflow, never the LLM) | No |
| "Guide me to room 203" | `DETERMINISTIC_RULE` (navigation proposal, Safety Supervisor approval required) | Yes |
| general small talk | `TINY_LOCAL_LLM` (`llm_qwen25_05b`, last resort) | No |
| `stop_palm` gesture | `DETERMINISTIC_RULE` (safety-relevant proposal) | Yes |
| unknown gesture | `DEGRADED_FALLBACK_TEMPLATE` (no action taken) | No |
| low-confidence emotion (< 0.6) | preserved as uncertain evidence, no behavior change | No |

## Required output fields — all present

Every `RouteDecision.to_dict()` carries `routeId`, `taskType`,
`chosenMethod`, `chosenModel`, `fallbackModel`, `reason`, `confidence`,
`estimatedLatencyMs`, `safetyRequired`, `dashboardEvent` — the exact
field set the brief requires, verified by
`tests/edge_ai/test_task_router.py::TestRouteDecisionFieldContract`.

## Safety integration

Every route that could touch navigation or actuation is passed through
`SafetySeparationGuard.classify()` before being returned as a
`RouteDecision`, so a caller can never accidentally skip that
classification step by calling the router directly — `dashboardEvent`
carries the resulting `safetyCategory`/`safetyBlocked` fields whenever a
safety-relevant route is chosen.

## Verification

`tests/edge_ai/test_task_router.py` — 10 tests, all passing: the field
contract, all 8 required routing examples, and cache-hit short-circuiting
via a real `CacheManager`.

## Known limitation (not fixed in this pass)

**GAP-E8, still open**: `llm_orchestrator_node.py` does not yet call
`TaskRouter` for real routing decisions — `pi_human_ai.yaml`'s
`resolution_order: [rule_engine, rag, llm]` remains unread by any live
code. Wiring the orchestrator to `bonbon_edge_ai_runtime` is a larger
cross-package integration, intentionally deferred rather than rushed as
a side effect of this phase — see
[`EDGE_AI_GAP_ANALYSIS.md`](EDGE_AI_GAP_ANALYSIS.md) GAP-E8.
