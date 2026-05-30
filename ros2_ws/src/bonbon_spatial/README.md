# bonbon_spatial

**Human-aware spatial reasoning** for the BonBon service robot. Consumes the
person tracks produced by the vision pipeline and turns them into a structured
world model, proxemic awareness, social-navigation hints, restricted-zone
alerts, path-blockage detection and short-horizon collision prediction.

This package is **perception/reasoning only** — it never commands motion. Its
outputs are consumed by `bonbon_navigation` (costmap / replanning),
`bonbon_behavior_engine` (decisions) and `bonbon_actuation` (proximity
derating).

---

## Responsibilities

| Capability | Module |
|---|---|
| Track entities in robot-frame coordinates with timeout eviction | `core/entity_tracker.py` |
| Proxemic personal-space estimation (Hall's zones) | `core/personal_space_estimator.py` |
| Named semantic zones + point-in-polygon lookup | `core/semantic_zone_manager.py` |
| Approach-pose planning (front/side, zone-aware) | `core/approach_pose_planner.py` |
| Social-navigation hint generation | `core/social_navigation_hints.py` |
| **Restricted-zone entry/exit alerts** (edge-triggered) | `core/restricted_zone_monitor.py` |
| **Forward-corridor blockage detection** (persistence-filtered) | `core/blockage_detector.py` |
| **Dynamic-obstacle collision prediction** (constant-velocity) | `core/dynamic_obstacle_predictor.py` |
| ROS2 LifecycleNode orchestration | `nodes/spatial_reasoning_node.py` |

---

## Architecture

```
/bonbon/vision/persons (PersonStateArray)
        │
        ▼
┌──────────────────────── SpatialReasoningNode ────────────────────────┐
│ EntityTracker ─┬─► PersonalSpaceEstimator ─► SocialNavigationHints    │
│                ├─► RestrictedZoneMonitor (uses SemanticZoneManager)   │
│                ├─► BlockageDetector                                   │
│                └─► DynamicObstaclePredictor                           │
└────────────────────────────────────────────────────────────────────────┘
   │              │                │                  │
   ▼              ▼                ▼                  ▼
/spatial/entities /spatial/relations /spatial/hints  /spatial/alerts
 (SpatialEntity)  (SpatialRelation) (SocialNav…Hint) (RiskEvent)
```

---

## Topics & Services

### Subscribed
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/vision/persons` | `bonbon_msgs/PersonStateArray` | person tracks |
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | safety context |

### Published
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/spatial/entities` | `bonbon_msgs/SpatialEntity` | tracked entities in world space |
| `/bonbon/spatial/relations` | `bonbon_msgs/SpatialRelation` | pairwise spatial relations |
| `/bonbon/spatial/hints` | `bonbon_msgs/SocialNavigationHint` | social slowdown/stop/reroute |
| `/bonbon/spatial/alerts` | `bonbon_msgs/RiskEvent` | **restricted-zone / blockage / collision** |

### Services
| Service | Type | Purpose |
|---|---|---|
| `~/get_world_model` | `bonbon_srvs/GetWorldModel` | snapshot of entities/relations/zones |
| `~/get_approach_pose` | `bonbon_srvs/GetApproachPose` | plan a socially-aware approach pose |
| `~/add_restricted_zone` | `bonbon_srvs/AddRestrictedZone` | add a zone at runtime |
| `~/remove_restricted_zone` | `bonbon_srvs/RemoveRestrictedZone` | remove a zone |

---

## Alert types (`/bonbon/spatial/alerts`, RiskEvent)

| `risk_type` | Severity | Trigger |
|---|---|---|
| `restricted_zone_entry` | HIGH | a tracked entity enters a `restricted` zone (edge-triggered) |
| `path_blocked` | MEDIUM | the forward corridor is occupied for ≥ `persistence_sec` |
| `collision_risk` | MEDIUM/HIGH | predicted closest approach within near-miss / collision distance |

---

## Reasoning models

- **Proxemics**: Hall's intimate / personal / social / public bands, with a
  larger safety margin for vulnerable categories (child, elderly, wheelchair).
- **Blockage**: an entity must sit inside the forward corridor
  (`±corridor_half_width_m × corridor_length_m`) for `persistence_sec` before a
  blockage is declared — transient crossings are ignored.
- **Prediction**: constant-velocity extrapolation over `horizon_sec`, sampling
  the predicted path and reporting the closest approach + time-to-closest. Risk
  is HIGH only when the entity is *converging* and predicted within the
  collision distance.

---

## Running

```bash
cd ros2_ws && colcon build --packages-select bonbon_spatial
ros2 launch bonbon_spatial spatial.launch.py

# Add a restricted zone at runtime
ros2 service call /spatial_reasoning_node/add_restricted_zone \
  bonbon_srvs/srv/AddRestrictedZone \
  "{zone_id: 'kitchen', zone_type: 'restricted',
    polygon: [{x: 1.0, y: -1.0}, {x: 3.0, y: -1.0}, {x: 3.0, y: 1.0}, {x: 1.0, y: 1.0}]}"

# Watch alerts
ros2 topic echo /bonbon/spatial/alerts
```

Runs fully in **simulation/mock mode**: it only needs `PersonStateArray`
messages (from the real vision node or a test publisher) — no hardware.

---

## Testing

```bash
cd ros2_ws/src/bonbon_spatial
python -m pytest tests/ -q          # 95 tests
```

- `test_entity_tracker.py` — tracking, eviction, approach flags
- `test_personal_space.py` — proxemic bands
- `test_semantic_zones.py` — point-in-polygon, zone types
- `test_approach_planner.py` — approach-pose geometry
- `test_restricted_zone_monitor.py` — entry/exit edge alerts
- `test_blockage_detector.py` — corridor occupancy + persistence
- `test_dynamic_obstacle_predictor.py` — trajectory + collision risk
- `tests/integration/test_spatial_integration.py` — full pipeline

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No entities published | No `PersonStateArray` on `/bonbon/vision/persons` | Start `bonbon_vision`; check QoS (sensor BEST_EFFORT). |
| Restricted-zone alerts never fire | No restricted zones loaded | Add zones via YAML `zones:` or `~/add_restricted_zone`; verify `zone_type: restricted`. |
| Blockage never declared | Person crosses too quickly, or corridor too narrow | Increase `corridor_half_width_m`, lower `persistence_sec`. |
| Blockage declared for passers-by | `persistence_sec` too low | Raise `persistence_sec` (default 1.5 s). |
| Collision alerts too frequent | Noisy velocity estimates | Increase `prediction.timestep_sec`; ensure vision provides smoothed velocity. |
| No collision prediction | Entities have zero velocity (`velocity_mps`) | Confirm the tracker/vision populates `velocity_mps` + `bearing_deg`. |
| Entities never expire | `entity_timeout_sec` too high | Lower it; default 5 s. |

### Diagnostics

Entity counts are logged each publish cycle. Restricted-zone entries and path
blockages are logged at WARN. All three alert classes are published as
`RiskEvent` on `/bonbon/spatial/alerts` with severity labels for the safety
supervisor / behaviour engine to consume.
