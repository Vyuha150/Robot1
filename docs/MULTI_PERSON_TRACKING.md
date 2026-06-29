# Multi-Person Tracking

Package: [`bonbon_multi_person_tracker`](../ros2_ws/src/bonbon_multi_person_tracker/README.md)

## Purpose

The single source of truth for "who is in the scene and what is their
lifecycle state." A repository audit found three independent, inconsistent
person trackers already in the codebase (`bonbon_vision`'s embedded
tracker, `bonbon_perception`'s, `bonbon_spatial`'s `EntityTracker`) — none
with re-identification across a track-loss gap or a lifecycle concept beyond
"present or evicted." This package is the one genuinely new capability;
every other multi-person package keys off its `person_track_id`.

## Architecture

```
bonbon_vision/vision_node
   │ /bonbon/vision/persons (PersonStateArray: track_id, face_id, position)
   ▼
multi_person_tracker_node
   │  MultiPersonSceneManager
   │    ├─ PersonLifecycleFSM (per person)
   │    ├─ IdentityAssociator (face_id / body-reid / spatial-proximity)
   │    └─ RecallBuffer (known-person continuity after a real departure)
   ▼
/bonbon/persons/tracks (PersonTrack)  +  /bonbon/persons/lifecycle_events
```

### Lifecycle states

```
new_candidate ──(N hits)──► present ──(interaction signal)──► active_interaction
     │ (never confirmed)         │ (missed)                         │ (missed)
     ▼                           ▼                                   ▼
 left_scene*            temporarily_lost ◄──────────────────────────┘
                              │ (re-matched: face/body/spatial)
                              ▼
                         reappeared ──(next cycle)──► present
```
`*` discarded silently — never published, since nothing meaningful arrived.

**Hard rule, enforced by tests:** a person is never declared gone from one
missed frame. `left_scene` only fires after `loss_grace_sec` (default 4 s)
of continuous absence.

## ROS2 interface

| Topic/Service | Type | Direction |
|---|---|---|
| `/bonbon/vision/persons` | `PersonStateArray` | sub |
| `/bonbon/safety/state` | `SafetyState` | sub |
| `/bonbon/persons/tracks` | `PersonTrack` | pub |
| `/bonbon/persons/lifecycle_events` | `std_msgs/String` | pub (transitions only) |
| `~/health_check` | `bonbon_srvs/HealthCheck` | service |

`PersonTrack.raw_track_id` bridges to `bonbon_vision`'s raw per-frame
`track_id` ("person_3") for sibling packages (`bonbon_affective_ai`) that
predate this one and still key off that space — empty while
`temporarily_lost`, since the raw ID is no longer trustworthy.

## Configuration

See [`config/multi_person_tracker_params.yaml`](../ros2_ws/src/bonbon_multi_person_tracker/bonbon_multi_person_tracker/config/multi_person_tracker_params.yaml).
Key knobs: `confirmation_hits` (2), `loss_grace_sec` (4.0),
`active_interaction_hold_sec` (3.0), `recall_window_sec` (300.0),
`max_persons` (20, resource bound), `privacy_mode`.

## Example

Two people in frame: Alice waves (gesture package calls
`mark_active_interaction`) and is promoted to `active_interaction`; Bob
walks behind a pillar and returns 2 seconds later — he's `temporarily_lost`
then `reappeared` with the SAME `person_track_id`, never a new one.

## Failure modes

| Failure | Behavior |
|---|---|
| `/bonbon/vision/persons` stale | Cycle treated as "nobody detected" — presence decays instead of persisting off a frozen frame. |
| Scene exceeds `max_persons` | New arrivals beyond the bound are dropped; existing tracks are never evicted to make room. |
| Two people standing close together | Tracker-churn merging against *active* records uses face/body evidence only — spatial proximity is deliberately excluded there, preventing two distinct nearby people from merging. |
| Known person leaves and returns later | New `person_track_id` (never resurrected), but `known_person_id` recovered via the `RecallBuffer` if face matches. |

## Tests

76 tests (`test_lifecycle_state_machine.py`, `test_identity_associator.py`,
`test_multi_person_scene_manager.py`, plus 4 integration scenarios). Plus 4
of the 25 cross-package scenarios (multi-person detection, person leaves,
new person arrives, old person reappears).

## Performance tuning

Target: **person tracking update ≤ 100 ms**. Measured p99 ≈ 0.2 ms at 5
simultaneous people — see [performance_tuning.md](performance_tuning.md).
The algorithm is O(detections × tracked people) per cycle; `max_persons`
bounds the worst case.

## Troubleshooting

- **Person never confirms (`new_candidate` forever)** — `confirmation_hits`
  set too high relative to `bonbon_vision`'s actual detection rate.
- **Two people keep merging into one record** — verify `bonbon_vision`'s
  face pipeline is actually populating `face_id`; without it only spatial
  proximity is available, which is excluded for active-pool merging by
  design, so this should not happen — if it does, it's a bug, not a tuning issue.
- **`left_scene` never fires** — check `loss_grace_sec` isn't unrealistically
  high, and confirm the vision feed is actually stopping, not just dropping
  one frame.
