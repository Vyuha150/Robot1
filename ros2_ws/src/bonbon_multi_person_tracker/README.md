# bonbon_multi_person_tracker

Person identity **lifecycle** tracking for the BonBon service robot: who is
in the scene, are they new, have they left, did they come back — kept
separate from raw per-frame detection (that's `bonbon_vision`'s job) and from
emotion/gesture/speech fusion (that's `bonbon_human_state_fusion`'s job).

## Why this package exists

A repository audit (2026-06) found **three independent person trackers**
already in the codebase (`bonbon_vision`'s embedded `_SimpleTracker`,
`bonbon_perception`'s 4-state `TrackState` tracker, and `bonbon_spatial`'s
`EntityTracker`) — none of them had a concept of re-identification across a
track-loss gap, a `temporarily_lost → reappeared` distinction, or persistent
known-identity continuity. This package fills that one genuine gap. It does
**not** detect people, run face recognition, or re-implement anything those
trackers already do — see [Data Flow](#data-flow) below.

## Architecture

```
bonbon_vision/vision_node
        │  /bonbon/vision/persons (PersonStateArray: track_id, face_id, position)
        ▼
bonbon_multi_person_tracker/multi_person_tracker_node
        │  /bonbon/persons/tracks (PersonTrack: person_track_id, lifecycle_state, …)
        │  /bonbon/persons/lifecycle_events (String, diagnostic, on real transitions only)
        ▼
bonbon_gesture, bonbon_speaker_intelligence, bonbon_human_state_fusion (consumers)
```

### Core modules (`bonbon_multi_person_tracker/core/`, no rclpy — pure Python)

| Module | Responsibility |
|---|---|
| `lifecycle_state_machine.py` | Per-person FSM: `new_candidate → present → active_interaction`, `→ temporarily_lost → reappeared/left_scene`. Owns all timeout/confidence logic. |
| `identity_associator.py` | Matches an incoming detection to an existing record: `FaceIdAssociator` (strongest), `BodyReIDAssociator` (pluggable, mock today — no body re-id model exists in this repo yet), `SpatialProximityAssociator` (speed-gated, used only for reappearance — see below). |
| `person_record.py` | Mutable per-person state container wrapping one FSM instance. |
| `multi_person_scene_manager.py` | The per-cycle orchestrator — the only class `multi_person_tracker_node.py` calls. |
| `temporary_id_allocator.py` | Monotonic `Person_N` label + UUID `person_track_id` generation. |
| `recall_buffer.py` | Short-term memory so a known person who genuinely left and returns later recovers `known_person_id` immediately, on a **brand-new** `person_track_id` (never a resurrected one). |

## Lifecycle states

```
new_candidate ──(N confirming hits)──► present ──(interaction signal)──► active_interaction
     │ (miss limit exceeded,                │ (missed frame)                  │ (missed frame)
     │  never confirmed)                     ▼                                  ▼
     └──────────────► left_scene*    temporarily_lost ◄─────────────────────────┘
                            ▲              │ (re-matched: face/body/spatial)
                            │              ▼
                  (grace window expired)  reappeared ──(next cycle, automatic)──► present
```
`*` A candidate that never confirms is discarded **silently** — it never
generates a `left_scene` message, because nothing meaningful "arrived" in the
first place.

**Hard rule:** a person is never declared gone from one missed frame. A miss
always goes through `temporarily_lost` first; `left_scene` only fires after
`loss_grace_sec` (default 4s) of continuous absence.

## Data flow — what this package does NOT re-implement

| Already exists, reused as-is | Lives in |
|---|---|
| Person/face detection, `track_id`, `face_id` | `bonbon_vision` (`/bonbon/vision/persons`) |
| Face recognition (known identity) | `bonbon_vision/face/face_pipeline.py` — `face_id` is passed straight through to `known_person_id` |
| Camera frame acquisition | `bonbon_hal` camera_node — **not touched** |

This package adds only: identity-continuity across loss, the 6-state
lifecycle, arrival/leaving/reappearance semantics, and the recall buffer.

## ROS2 interface

**Subscribes**
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/vision/persons` | `PersonStateArray` | per-frame detections (existing) |
| `/bonbon/safety/state` | `SafetyState` | reserved for future gating |

**Publishes**
| Topic | Type | Rate |
|---|---|---|
| `/bonbon/persons/tracks` | `PersonTrack` | one message per tracked person per cycle, `publish_rate_hz` (default 10 Hz) |
| `/bonbon/persons/lifecycle_events` | `std_msgs/String` | only on a real state transition |
| `/bonbon/persons/multi_person_tracker_node/health` | `ModuleHealth` | `health_rate_hz` (default 1 Hz) |

**Services**
| Service | Type |
|---|---|
| `~/health_check` | `bonbon_srvs/HealthCheck` |

**External hook** (called by sibling packages, not over ROS topics):
`MultiPersonSceneManager.mark_active_interaction(person_track_id)` — call this
from `bonbon_gesture` / `bonbon_speaker_intelligence` when a person addresses
the robot, to transition them into `active_interaction`.

## Configuration

See [`bonbon_multi_person_tracker/config/multi_person_tracker_params.yaml`](bonbon_multi_person_tracker/config/multi_person_tracker_params.yaml).
Key tunables: `confirmation_hits`, `loss_grace_sec`, `active_interaction_hold_sec`,
`recall_window_sec`, `max_persons` (resource bound — never grows unbounded),
`privacy_mode` (suppresses `known_person_id`/`face_id` in all output).

## Failure handling

| Failure | Behavior |
|---|---|
| `/bonbon/vision/persons` stale (> `vision_stale_timeout_sec`) | Cycle runs with an empty detection list — people age toward `temporarily_lost`/`left_scene` rather than staying falsely "present" off a frozen frame. |
| Scene exceeds `max_persons` | New arrivals beyond the bound are dropped (bounded resource use); existing tracks are never evicted to make room. |
| No face/body evidence available | Falls back to `SpatialProximityAssociator` for reappearance only — never used to merge two currently-active people (see below). |
| Two people standing close together | Tracker-churn merging against *active* (non-lost) records uses **only** face/body evidence, deliberately excluding spatial proximity — prevents merging two distinct nearby individuals into one record. |

## Tests

```
tests/test_lifecycle_state_machine.py        16 tests — FSM transitions, the "never one frame" rule
tests/test_identity_associator.py            13 tests — face/body/spatial matching, priority order
tests/test_multi_person_scene_manager.py     15 tests — orchestration: multi-person, leave, reappear, recall
tests/integration/test_multi_person_tracker_integration.py
                                               4 tests — realistic multi-cycle scenarios end-to-end
```
Run: `python -m pytest tests/ -q` (no rclpy required — all core logic is
pure Python with an injectable clock for deterministic timing tests).

## Performance target

Person-tracking update **< 100 ms** per cycle (target from the project's
performance brief). The core `MultiPersonSceneManager.update()` is O(n·m) in
detections × active records per cycle, bounded by `max_persons` (default 20)
— well within budget at any realistic occupancy for a service robot.

## Troubleshooting

- **A person never confirms (stuck in `new_candidate`)** — check
  `confirmation_hits` isn't set too high relative to the actual detection
  rate from `bonbon_vision`.
- **Two people keep merging into one record** — verify `face_id` is actually
  populated by `bonbon_vision`'s face pipeline; without it, only spatial
  proximity is available for reappearance, which is intentionally not used
  for active-pool merging (see Failure handling above) — so this should not
  happen for two simultaneously-tracked people. If it does, file it as a bug,
  not a tuning issue.
- **`left_scene` never fires** — check `loss_grace_sec` isn't set
  unrealistically high, and confirm `/bonbon/vision/persons` is actually
  stopping (not just dropping one frame).
