# Edge AI Test Coverage Report

Phase 15 summary of Phase 13's deliverable: 13 named test files under
[`tests/edge_ai/`](../tests/edge_ai/).

## The 13 files, all passing

| File | Tests | Covers |
|---|---|---|
| `test_model_registry.py` | 5 | merged-registry additivity, new-capability defaults/fallbacks, original 39 entries untouched |
| `test_task_router.py` | 10 | field contract, all 8 required routing examples, cache-hit short-circuit |
| `test_runtime_selector.py` | 5 | re-export identity, honest fallback-active reporting for the 3 new capabilities |
| `test_accelerator_manager.py` | 6 | capability guard, output envelope fields, freshness/staleness, honest empty status |
| `test_cache_manager.py` | 7 | RAG cache hit/miss/TTL/LRU, unified metrics, privacy-safe gate |
| `test_resource_guard.py` | 4 | field contract, thermal escalation (honestly conditioned on real-metrics availability), llm_guard identity, custom threshold |
| `test_safety_separation_guard.py` | 18 | 9 categories, never-allow table (7 tests), blocked-action dashboard visibility |
| `test_degraded_mode_manager.py` | 4 | combination logic, capability-fallback surfacing, delegation (not duplication) guard |
| `test_inference_scheduler.py` | 7 | real config loading, safety-critical bypass, bounded-queue drop-oldest, expired-task dropping |
| `test_three_pi_allocation.py` | 6 | 3 roles, forbidden lists, both cross-references resolve to real files/keys |
| `test_dashboard_edge_ai.py` | 13 | all 9 card views (honest-unavailable without collaborators, real data with them) |
| `test_download_plan.py` | 3 | merged-registry download plan, 3 new capabilities never auto-dispatched, Phase 11 scripts exist |
| `test_event_driven_processing.py` | 10 | GAP-E2/E13 regression guards, LLM-last-resort config, RAG/gesture/emotion event-driven behavior |

**94 tests total, 94 passing.**

## Cross-package regression (this brief's changes touched 7 packages)

`bonbon_edge_ai_runtime` (19 package-local tests, separate from the 94
above), `bonbon_operator_api` (233), `bonbon_llm` (297 passing standalone
per-file; 7 fail only when the full `tests/` directory is run together —
confirmed via `git stash` earlier this session to be a **pre-existing**
`rclpy.lifecycle.LifecycleNode` test-collection-order flake, not a
regression from this brief's work), `bonbon_navigation` (145),
`bonbon_behavior_engine` (170), `bonbon_motion_approval_gateway` (18).
Repo-root `tests/` (946 tests including `tests/edge_ai/`): **946 passed,
14 skipped** (hardware-gated, correctly not faked), 0 failed.

## A real gap found and fixed during this phase

`bonbon_edge_ai_runtime` had no `pytest.ini` — running its tests via
`cd ros2_ws/src/bonbon_edge_ai_runtime && pytest tests/` (rather than a
manually-set `PYTHONPATH`, which is how it had been smoke-tested during
Phases 2–11) failed with `ModuleNotFoundError: No module named
'bonbon_ai_model_registry'`. Fixed by adding a `pytest.ini` with
`pythonpath` entries for every sibling package this package imports
(directly or lazily), matching the pattern `bonbon_operator_api/pytest.ini`
already established.
