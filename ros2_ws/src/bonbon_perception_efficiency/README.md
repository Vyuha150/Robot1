# bonbon_perception_efficiency

Central coordination layer for perception efficiency. **Does not detect
anything itself** — coordinates existing perception modules by observing
their outputs and publishing advisory policy/budget recommendations. Never
commands another node, never bypasses the Safety Supervisor, never touches
actuation/navigation.

## Why this package exists

An efficiency audit (2026-06-30) found that confidence thresholds, frame
sampling rates, and stale-frame handling are all configured independently
per package with zero coordination, that `bonbon_safety`'s `ResourceMonitor`
(CPU/memory/disk sampling) was fully implemented but never wired to a topic,
and that nothing in the codebase reduces processing for background people
while prioritising the active speaker/focus person. This package adds that
coordination layer without touching any working module.

## Architecture

```
bonbon_safety (ResourceUsage, SafetyState)  ─┐
bonbon_hal (ThermalReadings)                 ─┤
bonbon_multi_person_tracker (PersonTrack)    ─┼──► PerceptionBudgetManager
bonbon_human_state_fusion (HumanState)       ─┤         │
every perception node (ModuleHealth)         ─┘         │
                                                          ▼
                                    /bonbon/perception_efficiency/{policy,budget,
                                                          degraded_mode,metrics}
```

### Core modules (`core/`, no rclpy)

| Module | Responsibility |
|---|---|
| `perception_budget_manager.py` | The orchestrator — owns one instance of everything below, combines them per cycle. |
| `load_shedding_controller.py` | Hysteresis-gated load level (normal→reduced→minimal→critical) from CPU/memory pressure + safety state. Escalation is immediate, de-escalation requires sustained recovery — no flapping. |
| `degraded_mode_manager.py` | System-wide degraded flag on SUSTAINED pressure (not one bad cycle) or an immediate safety FAULT/SAFE_STOP. |
| `confidence_policy_manager.py` | Recommended (not enforced) confidence thresholds, tightened under degraded/elevated-safety conditions, never below each signal's configured floor. |
| `frame_sampling_manager.py` | Recommended sample-every-Nth-frame per consumer, scaled by current load. |
| `active_person_focus_manager.py` | Per-person processing weight — the genuinely new capability the audit found missing: focus person = full rate, background people = reduced rate. Reuses `bonbon_behavior_engine`'s existing `select_focus_person()` rather than re-deriving who the focus is. |
| `stale_frame_dropper.py` | The one generic staleness check, factored out so a third package doesn't reimplement it. |
| `bounded_inference_queue.py` | Backpressure gate for unguarded `ThreadPoolExecutor.submit()` call sites (a real audit finding in `affective_ai_node`) — wrap, don't duplicate, the existing executor. |
| `temporal_smoothing_manager.py` | Generic majority-vote stability tracker for signals that don't already have one (`bonbon_gesture`'s own smoother is untouched). |
| `perception_metrics_aggregator.py` | Combines the `ModuleHealth` every perception node already publishes into one snapshot — no second metrics-collection pipeline. |

## Honest limitations

- **Advisory only.** No existing package has a live-reconfigure path to
  apply these recommendations automatically. `/bonbon/perception_efficiency/policy`
  and `/budget` are for dashboards and future integrations to read — wiring
  an existing node to actually *apply* a recommendation is a Phase 4
  runtime-optimization follow-up, not something this package can force.
  **Update:** `bonbon_human_state_fusion`'s `FocusPublishGate` is now a real
  consumer of the active-person focus weight specifically (see
  `bonbon_human_state_fusion/core/focus_publish_gate.py`) — background
  people's `HumanState` publishes at a reduced cadence; the focus person,
  new arrivals, and `left_scene` departures are never throttled. The
  `policy`/`budget` topics themselves are still otherwise advisory-only.

## ROS2 interface

**Subscribes:** `/bonbon/system/resource_usage`, `/bonbon/temperature/readings`
(reuses `bonbon_hal`'s existing publication — no second temperature sampling
pipeline), `/bonbon/safety/state`, `/bonbon/persons/tracks`,
`/bonbon/human/state`, plus `ModuleHealth` from
vision/multi_person_tracker/object_intelligence/speaker_intelligence/
human_state_fusion/speech.

**Publishes:** `/bonbon/perception_efficiency/policy` (`PerceptionPolicy`),
`/budget` (`PerceptionBudget`), `/degraded_mode` (`DegradedModeStatus`),
`/metrics` (`PerceptionEfficiencyMetrics`), `/bonbon/diagnostics/events`.

## Configuration

See [`config/perception_efficiency_params.yaml`](bonbon_perception_efficiency/config/perception_efficiency_params.yaml).

## Tests

77 tests across 9 core modules (`perception_budget_manager.py` is the
orchestrator, tested via integration-style cycles; every other module has
its own dedicated unit suite). Run: `python -m pytest tests/ -q`.

## Performance

This package adds negligible overhead by design — every core module is
dict/list arithmetic over a bounded number of tracked people/modules, no ML
inference. The whole point is to make OTHER packages cheaper to run, not to
add its own cost.
