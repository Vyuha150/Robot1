# Edge AI Runtime Architecture Report

Phase 15 summary of Phase 2's deliverable: the `bonbon_edge_ai_runtime`
ROS2 ament_python package at
[`ros2_ws/src/bonbon_edge_ai_runtime/`](../ros2_ws/src/bonbon_edge_ai_runtime/).

## Design decision: consolidation layer, not a rebuild

Before writing any code, [`docs/DUPLICATE_PIPELINE_AUDIT.md`](DUPLICATE_PIPELINE_AUDIT.md)
mapped the brief's literal 13-module spec against what already existed in
this repo. Result: only **2 of 13 modules were genuinely new logic**
(`task_router.py`, `safety_separation_guard.py`); the rest are thin
facades/re-exports over already-working, already-tested code
(`bonbon_ai_model_registry`, `bonbon_ai_runtime`, `bonbon_safety`,
`bonbon_perception_efficiency`, `bonbon_llm`). This kept the package
honest about what it actually contributes versus what it merely unifies.

## The 13 files (all present, all real)

| File | Role | New logic or facade? |
|---|---|---|
| `model_registry.py` | `load_merged()` combining the base 39-entry registry + 6 edge_ai-only entries | Facade (merge only) |
| `task_router.py` | Rule → cache → RAG → tiny-LLM → escalation routing | **New** |
| `runtime_selector.py` | Namespace re-export of `ModelRuntimeSelector` | Facade |
| `accelerator_manager.py` | Vision capability unification + output envelope | Facade + new envelope shape |
| `cache_manager.py` | Unified cache metrics + new `RagResultCache` | Facade + new RAG cache |
| `resource_guard.py` | Unifies `ResourceMonitor`/`LoadSheddingController`/`Pi2LLMGuard` | Facade |
| `safety_separation_guard.py` | 9-category action classifier, always fail-closed | **New** |
| `fallback_manager.py` | Re-export of `FallbackDecision`/`FallbackPolicy` | Facade |
| `degraded_mode_manager.py` | Bridges to the real perception-layer `DegradedModeManager` | Facade + combination logic |
| `inference_scheduler.py` | Priority-tiered dispatch reading real `pi_efficiency_profile.yaml` | Facade over config, new scheduling logic |
| `metrics_publisher.py` | Aggregates all components' state into one snapshot | New (pure aggregation) |
| `dashboard_publisher.py` | 9 dashboard-card JSON views | New (pure aggregation) |
| `config_loader.py` | Loads all 8 `config/edge_ai/*.yaml` | New (pure loading) |

Plus `nodes/edge_ai_runtime_node.py` — the one genuinely new ROS2 node,
publishing 6 status topics every 2s (default), following the repo's
established lazy-import/`std_msgs/String`-JSON pattern
(`model_health_monitor.py`'s precedent).

## The 8 config files

`config/edge_ai/{model_registry,task_routing,runtime_profiles,cache_policy,
resource_limits,safety_separation,degraded_modes,three_pi_allocation}.yaml`
— several deliberately reference an existing authoritative config
(`pi_efficiency_profile.yaml`, `model_registry.yaml`) rather than
re-declaring values, per the same consolidation principle.

## Cross-package import exception (documented, not silent)

`resource_guard.py` and `dashboard_publisher.py` cross-import other
packages' Python classes directly, which is an explicit, documented
exception to this repo's "packages talk only via ROS2 messages, not
direct Python imports" convention
([`load_shedding_controller.py`](../ros2_ws/src/bonbon_perception_efficiency/bonbon_perception_efficiency/core/load_shedding_controller.py)'s
own docstring). The exception is narrow and precedented: cross-cutting
**aggregation/dashboard-layer** code (matching `bonbon_ai_model_registry`'s
own established precedent) may read other packages' state for status
views, since it never feeds a live control loop — only a dashboard
snapshot or a routing *recommendation* (never a direct actuation).

## Verification

- All 13 files + the node byte-compile cleanly.
- `bonbon_edge_ai_runtime`'s own test suite: **19/19 passing**
  ([`tests/test_package_integration.py`](../ros2_ws/src/bonbon_edge_ai_runtime/tests/test_package_integration.py)).
- Cross-package regression (`bonbon_llm`, `bonbon_navigation`,
  `bonbon_behavior_engine`, `bonbon_motion_approval_gateway`,
  `bonbon_operator_api`): zero collateral breakage from this package's
  addition (see [`EDGE_AI_TEST_COVERAGE_REPORT.md`](EDGE_AI_TEST_COVERAGE_REPORT.md)).
